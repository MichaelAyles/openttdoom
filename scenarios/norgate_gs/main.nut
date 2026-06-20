/*
 * norprobe NOR: a TWO input NOR gate from OpenTTD track + a block signal, PROVEN
 * by sweeping all four input combinations and watching the reader train flip.
 *
 * Same primitive as the verified NOT, extended: the reader signal's protected
 * block (the INPUT block) now holds TWO input taps. A block signal is RED iff its
 * block is occupied by ANY train, so:
 *     reader passes  <=>  input block empty  <=>  NO input train present
 *                    <=>  a AND b both absent  ==  NOR(a, b).
 * The reader's final position is the output: past the signal (east depot) = 1,
 * held at the signal = 0. Read via GSVehicle.GetLocation, logged to the console.
 *
 * Layout (lane row Y, x increasing east):
 *   [west depot] approach [SIG @ SIGX] in-tap-a in-tap-b [SIG2 @ SIG2X] [east depot]
 *      BX-1               SIGX         INXA    INXB        SIG2X          EASTX
 *
 * BuildSignal(tile, front) permits travel FROM front INTO tile, so the eastbound
 * reader needs front = SIGX-1. The terminating SIG2 keeps the input block a proper
 * through block (a dead-end block keeps a normal signal red). Both facts verified
 * in the NOT experiment.
 *
 * Each of the four cases (a,b in {0,1}) builds the relevant input trains, runs a
 * fresh reader from the west depot, records whether it passed, then tears the
 * inputs and reader down. The full truth table is logged.
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

// Park an input train on tile (tx, Y) from a feeder depot just north of it.
// Returns the vehicle id (stopped on the tap), or null.
function NorProbeMain::ParkInput(inDepot, tx) {
    local v = GSVehicle.BuildVehicle(inDepot, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v)
            && GSMap.GetTileX(GSVehicle.GetLocation(v)) == tx
            && GSMap.GetTileY(GSVehicle.GetLocation(v)) == Y) {
            GSVehicle.StartStopVehicle(v);   // stop dead on the tap
            break;
        }
    }
    return v;
}

// Run a fresh reader west->east, return its final x (>SIGX means it passed).
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

// One truth-table row: set inputs a,b, run the reader, tear down. Returns out bit.
function NorProbeMain::Case(a, b) {
    if (a) this.inA = this.ParkInput(this.inDepotA, INXA);
    if (b) this.inB = this.ParkInput(this.inDepotB, INXB);
    GSController.Sleep(10);
    local fx = this.RunReader();
    local out = (fx > SIGX) ? 1 : 0;
    GSLog.Info("  NOR(a=" + a + ",b=" + b + ") -> reader x=" + fx
               + " (>SIGX=" + SIGX + "? " + (fx > SIGX) + ")  OUT=" + out);
    // teardown: the reader ended either in the east depot (sellable) or held at the
    // signal (on track, not sellable). If held, send it forward once inputs are
    // gone so it can reach the east depot and be sold.
    if (a && GSVehicle.IsValidVehicle(this.inA)) { GSVehicle.SellVehicle(this.inA); this.inA = null; }
    if (b && GSVehicle.IsValidVehicle(this.inB)) { GSVehicle.SellVehicle(this.inB); this.inB = null; }
    // let the now-unblocked reader roll into the east depot, then sell it.
    for (local s = 0; s < 16; s++) {
        GSController.Sleep(12);
        if (GSVehicle.IsStoppedInDepot(this.reader)) break;
    }
    if (GSVehicle.IsValidVehicle(this.reader)) GSVehicle.SellVehicle(this.reader);
    this.reader = null;
    GSController.Sleep(10);
    return out;
}

function NorProbeMain::Start() {
    GSLog.Info("norprobe NOR: START  SIGX=" + SIGX + " taps a=" + INXA + " b=" + INXB
               + " SIG2X=" + SIG2X + " EASTX=" + EASTX);
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID) {
        GSLog.Info("norprobe: waiting for company (run start_ai)...");
        GSController.Sleep(25);
    }
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    this.Prepare(BX - 2, Y - 2, EASTX + 1, Y + 2);

    local built = 0;
    for (local x = BX; x < EASTX; x++)
        if (GSRail.BuildRailTrack(GSMap.GetTileIndex(x, Y), GSRail.RAILTRACK_NE_SW)) built++;
    this.wDepot = GSMap.GetTileIndex(BX - 1, Y);
    local wok = GSRail.BuildRailDepot(this.wDepot, GSMap.GetTileIndex(BX, Y));
    this.eDepot = GSMap.GetTileIndex(EASTX, Y);
    local eok = GSRail.BuildRailDepot(this.eDepot, GSMap.GetTileIndex(EASTX - 1, Y));
    // eastbound-permissive reader signal + terminating signal (front = tile-1).
    local sok  = GSRail.BuildSignal(GSMap.GetTileIndex(SIGX, Y),  GSMap.GetTileIndex(SIGX - 1, Y),  GSRail.SIGNALTYPE_NORMAL);
    local s2ok = GSRail.BuildSignal(GSMap.GetTileIndex(SIG2X, Y), GSMap.GetTileIndex(SIG2X - 1, Y), GSRail.SIGNALTYPE_NORMAL);
    // two input feeder depots, north of each tap, joined into the line.
    this.inDepotA = GSMap.GetTileIndex(INXA, Y - 1);
    GSRail.BuildRailDepot(this.inDepotA, GSMap.GetTileIndex(INXA, Y));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INXA, Y), GSRail.RAILTRACK_NW_NE);
    this.inDepotB = GSMap.GetTileIndex(INXB, Y - 1);
    GSRail.BuildRailDepot(this.inDepotB, GSMap.GetTileIndex(INXB, Y));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INXB, Y), GSRail.RAILTRACK_NW_NE);
    GSLog.Info("norprobe NOR: built track=" + built + " wdepot=" + wok + " edepot=" + eok
               + " sig=" + sok + " sig2=" + s2ok);

    GSLog.Info("==== norprobe 2-input NOR truth table ====");
    local o00 = this.Case(0, 0);
    local o01 = this.Case(0, 1);
    local o10 = this.Case(1, 0);
    local o11 = this.Case(1, 1);
    GSLog.Info("==== NOR results: 00->" + o00 + " 01->" + o01 + " 10->" + o10 + " 11->" + o11 + " ====");
    local pass = (o00 == 1 && o01 == 0 && o10 == 0 && o11 == 0);
    GSLog.Info("norprobe NOR: " + (pass
               ? "PASS - all four rows match NOR(a,b). Two-input NOR computes in OpenTTD."
               : "FAIL/inconclusive"));
    GSLog.Info("norprobe NOR: DONE");
    // Reprint the latched verdict each idle cycle so an admin-port watcher
    // (python tools/ottd_admin.py watch) catches the result whenever it connects;
    // the sweep itself runs only once. This does not change the gate or the result.
    while (true) {
        GSController.Sleep(74);
        GSLog.Info("norprobe NOR (latched): 00->" + o00 + " 01->" + o01
                   + " 10->" + o10 + " 11->" + o11 + "  " + (pass ? "PASS" : "FAIL"));
    }
}

function NorProbeMain::Save() { return {}; }
function NorProbeMain::Load(version, data) {}
