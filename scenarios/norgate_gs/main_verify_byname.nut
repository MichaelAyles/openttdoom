/*
 * norgate verification harness (independent readout).
 *
 * Identical gate to scenarios/norgate_gs/main.nut: a 2-input NOR from track + a block
 * signal, output read by where a reader train stops (GSVehicle.GetLocation). The ONLY
 * change is the readout channel: instead of GSLog (which does not relay to the admin port
 * reliably here), it encodes the four raw reader-x positions into the COMPANY NAME, which
 * "rcon companies" reads directly. The NOR logic is then judged externally from the raw
 * positions: reader x > SIGX means the reader passed the signal (output 1), else 0.
 */
BX    <- 40;
SIGX  <- BX + 6;       // reader signal x (46)
INXA  <- SIGX + 1;     // input tap a (47)
INXB  <- SIGX + 2;     // input tap b (48)
SIG2X <- SIGX + 4;     // terminating signal x (50)
EASTX <- SIGX + 6;     // east depot x (52)
Y     <- 42;

class NorProbeMain extends GSController {
    company = null; eng = null;
    reader = null; inA = null; inB = null;
    wDepot = null; eDepot = null; inDepotA = null; inDepotB = null;
    constructor() {}
}
function NorProbeMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function NorProbeMain::Tx(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return -1;
    return GSMap.GetTileX(GSVehicle.GetLocation(v));
}
function NorProbeMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}
function NorProbeMain::ParkInput(inDepot, tx) {
    local v = GSVehicle.BuildVehicle(inDepot, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v)
            && GSMap.GetTileX(GSVehicle.GetLocation(v)) == tx
            && GSMap.GetTileY(GSVehicle.GetLocation(v)) == Y) {
            GSVehicle.StartStopVehicle(v); break;
        }
    }
    return v;
}
function NorProbeMain::RunReader() {
    this.reader = GSVehicle.BuildVehicle(this.wDepot, this.eng);
    GSOrder.AppendOrder(this.reader, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(this.reader)) GSVehicle.StartStopVehicle(this.reader);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(this.reader)) break;
    }
    local fx = BX - 1;
    for (local s = 0; s < 16; s++) { GSController.Sleep(18); fx = this.Tx(this.reader); }
    return fx;
}
// One row: set inputs, run reader, return the RAW reader x (the ground-truth observation).
function NorProbeMain::CaseFx(a, b) {
    if (a) this.inA = this.ParkInput(this.inDepotA, INXA);
    if (b) this.inB = this.ParkInput(this.inDepotB, INXB);
    GSController.Sleep(10);
    local fx = this.RunReader();
    if (a && GSVehicle.IsValidVehicle(this.inA)) { GSVehicle.SellVehicle(this.inA); this.inA = null; }
    if (b && GSVehicle.IsValidVehicle(this.inB)) { GSVehicle.SellVehicle(this.inB); this.inB = null; }
    for (local s = 0; s < 16; s++) { GSController.Sleep(12); if (GSVehicle.IsStoppedInDepot(this.reader)) break; }
    if (GSVehicle.IsValidVehicle(this.reader)) GSVehicle.SellVehicle(this.reader);
    this.reader = null;
    GSController.Sleep(10);
    return fx;
}
function NorProbeMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    GSCompany.SetName("NORGATE building");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    this.Prepare(BX - 2, Y - 2, EASTX + 1, Y + 2);
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, Y), GSRail.RAILTRACK_NE_SW);
    this.wDepot = GSMap.GetTileIndex(BX - 1, Y);
    GSRail.BuildRailDepot(this.wDepot, GSMap.GetTileIndex(BX, Y));
    this.eDepot = GSMap.GetTileIndex(EASTX, Y);
    GSRail.BuildRailDepot(this.eDepot, GSMap.GetTileIndex(EASTX - 1, Y));
    GSRail.BuildSignal(GSMap.GetTileIndex(SIGX, Y),  GSMap.GetTileIndex(SIGX - 1, Y),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(SIG2X, Y), GSMap.GetTileIndex(SIG2X - 1, Y), GSRail.SIGNALTYPE_NORMAL);
    this.inDepotA = GSMap.GetTileIndex(INXA, Y - 1);
    GSRail.BuildRailDepot(this.inDepotA, GSMap.GetTileIndex(INXA, Y));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INXA, Y), GSRail.RAILTRACK_NW_NE);
    this.inDepotB = GSMap.GetTileIndex(INXB, Y - 1);
    GSRail.BuildRailDepot(this.inDepotB, GSMap.GetTileIndex(INXB, Y));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INXB, Y), GSRail.RAILTRACK_NW_NE);

    local f00 = this.CaseFx(0, 0);
    local f01 = this.CaseFx(0, 1);
    local f10 = this.CaseFx(1, 0);
    local f11 = this.CaseFx(1, 1);
    // Encode the four RAW reader-x positions and SIGX into the company name, readable via
    // "rcon companies". External judge: x > SIGX means output 1 (reader passed the signal).
    local nm = "NORFX sig" + SIGX + " " + f00 + " " + f01 + " " + f10 + " " + f11;
    GSCompany.SetName(nm);
    while (true) { GSController.Sleep(74); GSCompany.SetName(nm); }
}
function NorProbeMain::Save() { return {}; }
function NorProbeMain::Load(version, data) {}
