/*
 * norchain: a TWO-GATE CHAIN computing OR(a,b) = NOT(NOR(a,b)), proving GATE
 * COMPOSITION on the verified single-gate primitive (scenarios/norgate_gs).
 *
 * The primitive (proven): a bit is a train present(1)/absent(0) on a block of
 * track. A normal block signal is RED iff its protected (through) block is occupied.
 * A reader train run west->east passes the signal iff the block is empty iff no
 * input train present == NOR. The output is read by WHERE the reader stops: x past
 * the signal == 1 (passed), held at/before it == 0. BuildSignal(tile, front) permits
 * travel FROM front INTO tile, so an eastbound reader needs front = SIGX-1, and the
 * protected block must be a through block (terminated by a second signal).
 *
 * COMPOSITION (validated by main_diag3.nut for the gate-1 park):
 *   Gate 1 is a 2-input NOR of primary inputs a,b on lane row gy1. Its reader is
 *   ordered to a far east depot; the MOMENT its x reaches the coupling tile CPLX we
 *   FREEZE it there (StartStopVehicle). diag3 confirmed: inputs absent -> reader
 *   passes SIG1X and parks at CPLX; an input present -> reader held at SIG1X (x <
 *   CPLX). So gate1 output 1 <=> a reader parked on CPLX, output 0 <=> nothing there.
 *   CPLX(gy1) is joined by a short vertical spur (no signal) to gate 2's input block
 *   on lane row gy2, so the two share ONE signal block. Therefore:
 *       gate1 passes -> reader parked on CPLX -> gate2 input OCCUPIED.
 *       gate1 held   -> nothing on CPLX       -> gate2 input EMPTY.
 *   Gate 2 is a NOT (one-input NOR) on lane row gy2: its reader passes iff its input
 *   block is empty iff gate1 did NOT pass. So gate2 = NOT(gate1) = OR(a,b).
 *
 * Expected composed truth table OR: 00->0, 01->1, 10->1, 11->1.
 *
 * STRUCTURE: to avoid any train teardown/reset between cases (which is fragile on a
 * coupled junction), each of the four cases (a,b) is built as an INDEPENDENT copy of
 * the chain at its own band of rows (BASE + case*BAND). Inputs for that case are
 * pre-parked, then both readers are run and their final x recorded. Nothing is sold;
 * each case is physically separate, so cases cannot pollute each other.
 *
 * Readout: GSLog does not relay reliably here, and company names are length-limited
 * (long names silently fail to set), so the four gate-2 reader final x (the OR
 * output) are encoded SHORT into the COMPANY NAME, read via "rcon companies", and
 * updated live. External judge: gate2 x > SIG2X => OR output 1.
 */

// X geometry shared by every case-copy (validated by diag3 for gate 1).
G1BX    <- 30;            // gate1 west depot at G1BX-1 (29)
SIG1X   <- G1BX + 6;      // gate1 NOR signal x (36)
INXA    <- SIG1X + 1;     // input tap a (37)
INXB    <- SIG1X + 2;     // input tap b (38)
SIG1TX  <- SIG1X + 4;     // gate1 terminating signal x (40)
CPLX    <- SIG1X + 6;     // coupling tile: a PASSING gate1 reader is frozen here (42)
G1EASTX <- CPLX + 4;      // gate1 reachable east depot x (46)
G2BX    <- 33;           // gate2 west depot at G2BX-1 (32)
SIG2X   <- CPLX - 2;     // gate2 NOR/NOT signal x (40); input block 41,42,43
SIG2TX  <- CPLX + 2;     // gate2 terminating signal x (44); CPLX=42 inside 41..43
G2EASTX <- SIG2TX + 4;   // gate2 east depot x (48)

// Y banding: each case gets gy1 (gate1 lane) and gy2 = gy1+3 (gate2 lane).
BASE    <- 30;           // first case's gate1 lane row
BAND    <- 8;            // rows between successive case bands

class NorChainMain extends GSController {
    company = null; eng = null;
    constructor() {}
}

function NorChainMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function NorChainMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function NorChainMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function NorChainMain::Say(s) { GSCompany.SetName(s); }
function NorChainMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Build one independent chain copy at gate1 lane row gy1. Returns the depot/feeder
// tile indices needed to run it, as a table.
function NorChainMain::BuildCopy(gy1) {
    local gy2 = gy1 + 3;
    // gate 1 lane
    for (local x = G1BX; x < G1EASTX; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy1), GSRail.RAILTRACK_NE_SW);
    local g1wDepot = GSMap.GetTileIndex(G1BX - 1, gy1);
    GSRail.BuildRailDepot(g1wDepot, GSMap.GetTileIndex(G1BX, gy1));
    local g1eDepot = GSMap.GetTileIndex(G1EASTX, gy1);
    GSRail.BuildRailDepot(g1eDepot, GSMap.GetTileIndex(G1EASTX - 1, gy1));
    GSRail.BuildSignal(GSMap.GetTileIndex(SIG1X, gy1),  GSMap.GetTileIndex(SIG1X - 1, gy1),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(SIG1TX, gy1), GSMap.GetTileIndex(SIG1TX - 1, gy1), GSRail.SIGNALTYPE_NORMAL);
    local inDepotA = GSMap.GetTileIndex(INXA, gy1 - 1);
    GSRail.BuildRailDepot(inDepotA, GSMap.GetTileIndex(INXA, gy1));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INXA, gy1), GSRail.RAILTRACK_NW_NE);
    local inDepotB = GSMap.GetTileIndex(INXB, gy1 - 1);
    GSRail.BuildRailDepot(inDepotB, GSMap.GetTileIndex(INXB, gy1));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INXB, gy1), GSRail.RAILTRACK_NW_NE);
    // gate 2 lane
    for (local x = G2BX; x < G2EASTX; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy2), GSRail.RAILTRACK_NE_SW);
    local g2wDepot = GSMap.GetTileIndex(G2BX - 1, gy2);
    GSRail.BuildRailDepot(g2wDepot, GSMap.GetTileIndex(G2BX, gy2));
    local g2eDepot = GSMap.GetTileIndex(G2EASTX, gy2);
    GSRail.BuildRailDepot(g2eDepot, GSMap.GetTileIndex(G2EASTX - 1, gy2));
    GSRail.BuildSignal(GSMap.GetTileIndex(SIG2X, gy2),  GSMap.GetTileIndex(SIG2X - 1, gy2),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(SIG2TX, gy2), GSMap.GetTileIndex(SIG2TX - 1, gy2), GSRail.SIGNALTYPE_NORMAL);
    // coupling spur (no signal): vertical track x=CPLX from gy1 to gy2 with corners.
    for (local y = gy1; y <= gy2; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(CPLX, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(CPLX, gy1), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(CPLX, gy2), GSRail.RAILTRACK_NW_NE);
    return { gy1 = gy1, gy2 = gy2, g1wDepot = g1wDepot, g1eDepot = g1eDepot,
             g2wDepot = g2wDepot, g2eDepot = g2eDepot, inDepotA = inDepotA, inDepotB = inDepotB };
}

// Park an input train on tile (tx, gy1) from a feeder depot just north of it.
function NorChainMain::ParkInput(inDepot, tx, gy1) {
    local v = GSVehicle.BuildVehicle(inDepot, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy1), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && GSMap.GetTileX(GSVehicle.GetLocation(v))==tx && GSMap.GetTileY(GSVehicle.GetLocation(v))==gy1) { GSVehicle.StartStopVehicle(v); break; }
    }
    return v;
}

// Run gate1 reader on copy c, freezing the moment x reaches CPLX on row gy1.
function NorChainMain::RunG1Freeze(c) {
    local v = GSVehicle.BuildVehicle(c.g1wDepot, this.eng);
    GSOrder.AppendOrder(v, c.g1eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 30; s++) {
        GSController.Sleep(10);
        fx = this.Tx(v);
        if (fx >= CPLX && this.Ty(v) == c.gy1) { GSVehicle.StartStopVehicle(v); fx = this.Tx(v); break; }
    }
    return fx;
}

// Run gate2 reader on copy c; return its final x.
function NorChainMain::RunG2Reader(c) {
    local v = GSVehicle.BuildVehicle(c.g2wDepot, this.eng);
    GSOrder.AppendOrder(v, c.g2eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 20; s++) { GSController.Sleep(12); fx = this.Tx(v); }
    return fx;
}

// Run one case-copy: pre-park inputs a,b, run gate1 (parks at CPLX iff it passes),
// then run gate2 (reads coupling). Returns [g1x, g2x].
function NorChainMain::RunCase(c, a, b) {
    if (a) this.ParkInput(c.inDepotA, INXA, c.gy1);
    if (b) this.ParkInput(c.inDepotB, INXB, c.gy1);
    GSController.Sleep(8);
    local g1 = this.RunG1Freeze(c);
    GSController.Sleep(8);
    local g2 = this.RunG2Reader(c);
    return [g1, g2];
}

function NorChainMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("CHAIN build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    // Flatten the whole footprint: x from G1BX-2..G2EASTX+1, y from BASE-2 to the
    // last band's gate2 lane +2.
    local lastGy2 = BASE + 3*BAND + 3;
    this.Prepare(G1BX - 2, BASE - 2, G2EASTX + 1, lastGy2 + 2);

    // Build four independent copies, one per case.
    local copies = [];
    for (local k = 0; k < 4; k++) copies.append(this.BuildCopy(BASE + k*BAND));
    this.Say("CHAIN built4");

    local r00 = this.RunCase(copies[0], 0, 0);
    this.Say("c00 " + r00[0] + "/" + r00[1]);
    local r01 = this.RunCase(copies[1], 0, 1);
    this.Say("c01 " + r01[0] + "/" + r01[1]);
    local r10 = this.RunCase(copies[2], 1, 0);
    this.Say("c10 " + r10[0] + "/" + r10[1]);
    local r11 = this.RunCase(copies[3], 1, 1);

    // Encode SHORT: four gate2 final x (the OR output). Judge: x > SIG2X => OR 1.
    local nm = "OR s" + SIG2X + " " + r00[1] + " " + r01[1] + " " + r10[1] + " " + r11[1];
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function NorChainMain::Save() { return {}; }
function NorChainMain::Load(version, data) {}
