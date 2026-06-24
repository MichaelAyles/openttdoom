/*
 * stageA: a FIXED THREE-GATE CHAIN, proving the norchain fixed signal-free coupling
 * composes PAST two gates. Network:
 *     g0 = NOR(a, b)   -> n0
 *     g1 = NOR(n0, a)  -> n1     (reads coupling n0 from g0 AND a fresh primary a tap)
 *     g2 = NOR(n1)     -> y      (a NOT)
 * Expected y over (a,b)=00,01,10,11: 1,0,1,1 (judged from RAW g2 reader x).
 *
 * GEOMETRY reused VERBATIM from norchain (scenarios/norchain_gs):
 *   - a bit is train-presence on a protected through-block; a reader passes a normal
 *     block signal iff its input block is empty (== NOR of the present inputs).
 *   - BuildSignal(tile, front) permits travel FROM front INTO tile, so an eastbound
 *     reader needs front = SIG-1; the input block is terminated by a SECOND signal.
 *   - a PASSING driver reader is FROZEN (StartStopVehicle) the moment its x reaches the
 *     driver's coupling tile CPL (the dead-end hold does not park it cleanly).
 *   - a SHORT PURE-VERTICAL signal-free spur joins the driver CPL tile down into the
 *     consumer's input block (3 rows below), merging the two signal blocks. So
 *     "driver output 1" == a train parked in the consumer's input block.
 * Each consumer marches +4 east and +3 down from its driver, exactly norchain's stage.
 *
 * NO per-gate train is re-parked or disposed between reads: per input combo we build ONE
 * fresh chain copy at its own band of rows, pre-park the primary inputs ONCE, then run the
 * three gate readers in order (each frozen at its CPL if it passes). Nothing is torn down
 * between gate reads; the four combos are SEPARATE physical copies (teardown on a coupled
 * junction hangs the script, exactly as norchain found).
 */

// ---- g0 absolute geometry (the norchain gate-1 cell), per case row gy0 ----
G0BX   <- 30;          // g0 west depot at G0BX-1 (29)
SIG0X  <- G0BX + 6;    // g0 reader signal x (36)
IN0XA  <- SIG0X + 1;   // g0 primary input tap a (37)
IN0XB  <- SIG0X + 2;   // g0 primary input tap b (38)
SIG0TX <- SIG0X + 4;   // g0 terminating signal x (40)
CPL0   <- SIG0TX + 1;  // g0 coupling/freeze tile (41), the FIRST tile past the terminating
                       // signal. A passing reader is frozen here the instant it clears the
                       // terminating signal, ON the spur column, before it can roll on.
G0EAST <- CPL0 + 6;    // g0 east depot x (47), FAR past CPL0 so a passing reader rests on
                       // open track to be frozen, not rolled into a near depot.

// ---- g1 cell, 3 rows below g0, coupling n0 lands at CPL0 ----
//   consumer relations: SIG=CPL_driver-2, block=[CPL_d-1,CPL_d,CPL_d+1], SIGT=CPL_d+2,
//   CPL=SIGT+1. g1's input block is [40,41,42]; coupling n0 lands at CPL0=41; the fresh
//   primary 'a' tap goes at block col 40 (distinct from the coupling).
SIG1X  <- CPL0 - 2;    // g1 reader signal x (39); input block 40,41,42
IN1XA  <- CPL0 - 1;    // g1 primary input tap a (40)
G1BX   <- SIG1X - 7;   // g1 west depot at G1BX-1 (31)
SIG1TX <- CPL0 + 2;    // g1 terminating signal x (43); CPL0=41 inside 40..42
CPL1   <- SIG1TX + 1;  // g1 coupling/freeze tile (44), first tile past terminating signal
G1EAST <- CPL1 + 6;    // g1 east depot x (50), FAR past CPL1 (driver needs a far depot)

// ---- g2 cell (NOT), 3 rows below g1, coupling n1 lands at CPL1 ----
SIG2X  <- CPL1 - 2;    // g2 reader signal x (42); input block 43,44,45
SIG2TX <- CPL1 + 2;    // g2 terminating signal x (46); CPL1=44 inside 43..45
G2BX   <- SIG2X - 7;   // g2 west depot at G2BX-1 (34)
CPL2   <- SIG2TX + 1;  // g2 coupling tile (47) (unused downstream; freeze harmless)
G2EAST <- SIG2TX + 4;  // g2 east depot x (50)

// Y banding: each combo gets gy0 (g0 lane); g1 = gy0+3; g2 = gy0+6.
BASE   <- 30;          // first combo's g0 lane row
BAND   <- 12;          // rows between successive combo bands (3 lanes + slack)

class StageAMain extends GSController {
    company = null; eng = null;
    constructor() {}
}

function StageAMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function StageAMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function StageAMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function StageAMain::Say(s) { GSCompany.SetName(s); }
function StageAMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Build a horizontal gate lane: track bx..eastx-1 on row gy, west+east depots, reader
// signal at sigx (front sigx-1), terminating signal at sigtx (front sigtx-1).
function StageAMain::BuildLane(bx, eastx, gy, sigx, sigtx) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
    local wd = GSMap.GetTileIndex(bx - 1, gy);
    GSRail.BuildRailDepot(wd, GSMap.GetTileIndex(bx, gy));
    local ed = GSMap.GetTileIndex(eastx, gy);
    GSRail.BuildRailDepot(ed, GSMap.GetTileIndex(eastx - 1, gy));
    GSRail.BuildSignal(GSMap.GetTileIndex(sigx, gy),  GSMap.GetTileIndex(sigx - 1, gy),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(sigtx, gy), GSMap.GetTileIndex(sigtx - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    return { wd = wd, ed = ed };
}

// An input feeder depot just north of tap tile (tx, gy), joined into the lane.
function StageAMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// A pure-vertical signal-free coupling spur in column cplx, from driver row gyd down to
// consumer row gyc, with corner pieces joining each lane (exactly norchain's spur).
function StageAMain::BuildSpur(cplx, gyd, gyc) {
    for (local y = gyd; y <= gyc; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, gyd), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, gyc), GSRail.RAILTRACK_NW_NE);
}

// Build one independent chain copy at g0 lane row gy0. Returns a table of the run handles.
function StageAMain::BuildCopy(gy0) {
    local gy1 = gy0 + 3;
    local gy2 = gy0 + 6;
    local l0 = this.BuildLane(G0BX, G0EAST, gy0, SIG0X, SIG0TX);
    local l1 = this.BuildLane(G1BX, G1EAST, gy1, SIG1X, SIG1TX);
    local l2 = this.BuildLane(G2BX, G2EAST, gy2, SIG2X, SIG2TX);
    // g0 primary input feeders a,b
    local fa0 = this.FeederDepot(IN0XA, gy0);
    local fb0 = this.FeederDepot(IN0XB, gy0);
    // g1 primary input feeder a (at IN1XA, north of g1 lane)
    local fa1 = this.FeederDepot(IN1XA, gy1);
    // coupling spurs: g0->g1 at CPL0 (gy0..gy1), g1->g2 at CPL1 (gy1..gy2)
    this.BuildSpur(CPL0, gy0, gy1);
    this.BuildSpur(CPL1, gy1, gy2);
    return { gy0 = gy0, gy1 = gy1, gy2 = gy2,
             l0 = l0, l1 = l1, l2 = l2, fa0 = fa0, fb0 = fb0, fa1 = fa1 };
}

// Park an input train on tile (tx, gy) from feeder depot d just north of it. Freeze on tap.
function StageAMain::ParkInput(d, tx, gy) {
    local v = GSVehicle.BuildVehicle(d, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && GSMap.GetTileX(GSVehicle.GetLocation(v))==tx && GSMap.GetTileY(GSVehicle.GetLocation(v))==gy) { GSVehicle.StartStopVehicle(v); break; }
    }
    return v;
}

// Run a gate reader from west depot wd toward east depot ed on row gy; freeze the moment it
// clears the terminating signal (x >= cpl) OR has passed the reader signal and started down
// the coupling spur (left row gy after passing sigx). A HELD reader (input occupied) never
// reaches cpl and stays on row gy at sigx-1, so it is not frozen and rests there. Returns x.
function StageAMain::RunFreeze(wd, ed, gy, sigx, cpl) {
    local v = GSVehicle.BuildVehicle(wd, this.eng);
    GSOrder.AppendOrder(v, ed, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    // Poll tightly so we catch the passing reader on/near the coupling tile before it rolls
    // to the far depot; freezing it ON the coupling spur column or its merged block is what
    // occupies the consumer's input.
    local fx = -1;
    for (local s = 0; s < 160; s++) {
        GSController.Sleep(3);
        fx = this.Tx(v);
        local ty = this.Ty(v);
        if (fx < 0) continue;
        local diverted = (fx > sigx && ty != gy);   // passed reader sig, then left the row
        if (fx >= cpl || diverted) { GSVehicle.StartStopVehicle(v); fx = this.Tx(v); break; }
    }
    return fx;
}

// Run the FINAL gate (g2) reader; no freeze needed, just record where it stops. Returns x.
function StageAMain::RunReader(wd, ed) {
    local v = GSVehicle.BuildVehicle(wd, this.eng);
    GSOrder.AppendOrder(v, ed, GSOrder.OF_NON_STOP_INTERMEDIATE);
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

// Run one combo: pre-park primary inputs, then run g0, g1, g2 readers in order.
// Returns [g0x, g1x, g2x].
function StageAMain::RunCase(c, a, b) {
    // g0 primary inputs a,b ; g1 primary input a (a separate train).
    if (a) this.ParkInput(c.fa0, IN0XA, c.gy0);
    if (b) this.ParkInput(c.fb0, IN0XB, c.gy0);
    if (a) this.ParkInput(c.fa1, IN1XA, c.gy1);
    GSController.Sleep(8);
    local g0 = this.RunFreeze(c.l0.wd, c.l0.ed, c.gy0, SIG0X, CPL0);
    GSController.Sleep(8);
    local g1 = this.RunFreeze(c.l1.wd, c.l1.ed, c.gy1, SIG1X, CPL1);
    GSController.Sleep(8);
    local g2 = this.RunReader(c.l2.wd, c.l2.ed);
    return [g0, g1, g2];
}

function StageAMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("STGA build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastGy2 = BASE + 3*BAND + 6;
    this.Prepare(G0BX - 2, BASE - 2, G2EAST + 1, lastGy2 + 2);

    local copies = [];
    for (local k = 0; k < 4; k++) copies.append(this.BuildCopy(BASE + k*BAND));
    this.Say("STGA built4");

    local r00 = this.RunCase(copies[0], 0, 0);
    this.Say("a00 " + r00[0] + "/" + r00[1] + "/" + r00[2]);
    local r01 = this.RunCase(copies[1], 0, 1);
    this.Say("a01 " + r01[0] + "/" + r01[1] + "/" + r01[2]);
    local r10 = this.RunCase(copies[2], 1, 0);
    this.Say("a10 " + r10[0] + "/" + r10[1] + "/" + r10[2]);
    local r11 = this.RunCase(copies[3], 1, 1);

    // Encode SHORT: the four g2 (output) final x. Judge: x > SIG2X => output 1.
    local nm = "STGA s" + SIG2X + " " + r00[2] + " " + r01[2] + " " + r10[2] + " " + r11[2];
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function StageAMain::Save() { return {}; }
function StageAMain::Load(version, data) {}
