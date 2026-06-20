/*
 * norprobe: ONE physical NOT gate, POKED twice on the SAME structure, proving it
 * computes. The gate is OpenTTD track + a block signal; the readout is a reader
 * train's position, observed from the GameScript via GSVehicle.GetLocation.
 *
 * Single lane (x increases east), on a levelled clear strip:
 *
 *   [west depot] approach [SIG @ SIGX] INPUT-block [SIG2 @ SIG2X] [east depot]
 *      BX-1               SIGX        SIGX+1..SIG2X-1  SIG2X        EASTX
 *
 *   BuildSignal(tile, front) permits travel FROM front INTO tile, so a signal at
 *   SIGX with front=SIGX-1 lets an eastbound train pass and protects the block it
 *   enters (the INPUT block, east). The reader is ordered into the east depot; it
 *   reaches it iff the input block is empty:
 *       A=0 (input block empty)    -> SIG green -> reader passes  -> x reaches EASTX  -> out 1
 *       A=1 (input train present)  -> SIG red   -> reader held    -> x stuck at SIGX-1 -> out 0
 *   That is NOT(A). A second terminating signal SIG2 keeps the input block a
 *   proper through-block (a dead-end block keeps a normal signal red regardless).
 *
 * EXPERIMENT, two pokes on the same gate:
 *   POKE 1: A=0. Release reader, sample, expect it past the signal (out=1).
 *   POKE 2: A=1. Recall reader to west depot, park an input train in the input
 *           block, release reader again, expect it HELD at the signal (out=0).
 *   The SAME reader flips its outcome with the poked input: NOT computed.
 */

BX    <- 40;
SIGX  <- BX + 6;       // reader signal x (46)
INX   <- SIGX + 2;     // input train parks here (48)
SIG2X <- SIGX + 4;     // terminating signal x (50)
EASTX <- SIGX + 6;     // east depot x (52)
Y     <- 42;           // the single lane row

class NorProbeMain extends GSController {
    company = null; eng = null;
    reader = null; input = null;
    wDepot = null; eDepot = null; inDepot = null;
    constructor() {}
}

function NorProbeMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function NorProbeMain::Loc(v) {
    if (v == null) return "none";
    if (!GSVehicle.IsValidVehicle(v)) return "invalid";
    local t = GSVehicle.GetLocation(v);
    return "x" + GSMap.GetTileX(t) + " st=" + GSVehicle.GetState(v) + " spd=" + GSVehicle.GetCurrentSpeed(v);
}
function NorProbeMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Run the reader from the west depot toward the east depot, sample its final x.
// Returns the final tile x (SIGX-1 if held at the signal, EASTX if it passed).
function NorProbeMain::RunReader(label) {
    // (re)build the reader in the west depot if needed
    if (this.reader == null || !GSVehicle.IsValidVehicle(this.reader)) {
        this.reader = GSVehicle.BuildVehicle(this.wDepot, this.eng);
        GSOrder.AppendOrder(this.reader, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
        GSController.Sleep(5);   // let the build/order register before starting
    }
    // release it from the depot; retry until it actually leaves (spd>0 or off depot).
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(this.reader)) GSVehicle.StartStopVehicle(this.reader);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(this.reader)) break;
    }
    GSLog.Info("norprobe: [" + label + "] reader released, inDepot="
               + GSVehicle.IsStoppedInDepot(this.reader));
    local fx = BX - 1;
    for (local s = 0; s < 16; s++) {
        GSController.Sleep(18);
        fx = GSMap.GetTileX(GSVehicle.GetLocation(this.reader));
        GSLog.Info("    [" + label + "] s" + s + " reader " + this.Loc(this.reader)
                   + " input " + this.Loc(this.input));
    }
    return fx;
}

function NorProbeMain::Start() {
    GSLog.Info("norprobe: START single-gate poke test  SIGX=" + SIGX + " INX=" + INX
               + " SIG2X=" + SIG2X + " EASTX=" + EASTX + " Y=" + Y);
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

    // Build the gate: track, depots, two eastbound-permissive signals, input spur.
    local built = 0;
    for (local x = BX; x < EASTX; x++)
        if (GSRail.BuildRailTrack(GSMap.GetTileIndex(x, Y), GSRail.RAILTRACK_NE_SW)) built++;
    this.wDepot = GSMap.GetTileIndex(BX - 1, Y);
    local wok = GSRail.BuildRailDepot(this.wDepot, GSMap.GetTileIndex(BX, Y));
    this.eDepot = GSMap.GetTileIndex(EASTX, Y);
    local eok = GSRail.BuildRailDepot(this.eDepot, GSMap.GetTileIndex(EASTX - 1, Y));
    local sok = GSRail.BuildSignal(GSMap.GetTileIndex(SIGX, Y), GSMap.GetTileIndex(SIGX - 1, Y),
                                   GSRail.SIGNALTYPE_NORMAL);
    local s2ok = GSRail.BuildSignal(GSMap.GetTileIndex(SIG2X, Y), GSMap.GetTileIndex(SIG2X - 1, Y),
                                    GSRail.SIGNALTYPE_NORMAL);
    // input feeder depot north of INX, plus the connecting corner into the line.
    this.inDepot = GSMap.GetTileIndex(INX, Y - 1);
    GSRail.BuildRailDepot(this.inDepot, GSMap.GetTileIndex(INX, Y));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(INX, Y), GSRail.RAILTRACK_NW_NE);
    GSLog.Info("norprobe: gate built track=" + built + " wdepot=" + wok + " edepot=" + eok
               + " sig=" + sok + " sig2=" + s2ok
               + " sigtype=" + GSRail.GetSignalType(GSMap.GetTileIndex(SIGX, Y), GSMap.GetTileIndex(SIGX - 1, Y)));

    // Each poke uses a FRESH reader built in the west depot, so it always starts
    // its run from the west and approaches the signal once. The input bit is
    // toggled by building/selling an input train on the SAME gate, so this is one
    // physical gate poked twice. We run A=0 first: that reader ends in the EAST
    // depot, where it can be sold cleanly before the A=1 run (a train on open
    // track cannot be sold, only one stopped in a depot).

    // ---- POKE 1: A = 0 (input block empty) ----
    GSLog.Info("norprobe: POKE A=0 (no input train)");
    local out0 = this.RunReader("A=0");
    GSLog.Info("norprobe: POKE A=0 -> reader final x=" + out0
               + " => NOT(0)=" + ((out0 > SIGX) ? 1 : 0));
    // the A=0 reader passed into the east depot; wait for it to be in-depot, sell it.
    for (local s = 0; s < 12; s++) {
        if (GSVehicle.IsStoppedInDepot(this.reader)) break;
        GSController.Sleep(10);
    }
    GSLog.Info("norprobe: A=0 reader parked east, inDepot="
               + GSVehicle.IsStoppedInDepot(this.reader) + " " + this.Loc(this.reader));
    GSVehicle.SellVehicle(this.reader);
    this.reader = null;
    GSController.Sleep(10);

    // ---- POKE 2: A = 1 (park an input train in the input block) ----
    this.input = GSVehicle.BuildVehicle(this.inDepot, this.eng);
    GSOrder.AppendOrder(this.input, GSMap.GetTileIndex(INX, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(this.input)) GSVehicle.StartStopVehicle(this.input);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(this.input)
            && GSMap.GetTileX(GSVehicle.GetLocation(this.input)) == INX
            && GSMap.GetTileY(GSVehicle.GetLocation(this.input)) == Y) {
            GSVehicle.StartStopVehicle(this.input);   // stop it dead on INX (A=1)
            break;
        }
    }
    GSLog.Info("norprobe: POKE A=1 input parked: " + this.Loc(this.input));
    local out1 = this.RunReader("A=1");
    GSLog.Info("norprobe: POKE A=1 -> reader final x=" + out1
               + " => NOT(1)=" + ((out1 > SIGX) ? 1 : 0));

    // ---- VERDICT ----
    local n0 = (out0 > SIGX) ? 1 : 0;
    local n1 = (out1 > SIGX) ? 1 : 0;
    GSLog.Info("==== norprobe NOT-gate truth table (one physical gate, poked) ====");
    GSLog.Info("   A=0 -> NOT=" + n0 + "   (reader reached x" + out0 + ", east depot x" + EASTX + ")");
    GSLog.Info("   A=1 -> NOT=" + n1 + "   (reader held at x" + out1 + ", signal x" + SIGX + ")");
    GSLog.Info("   RESULT: " + ((n0 == 1 && n1 == 0)
               ? "PASS - the SAME gate flipped output when the input was poked. NOT computes."
               : "FAIL/inconclusive"));
    GSLog.Info("norprobe: DONE");
    while (true) { GSController.Sleep(74); }
}

function NorProbeMain::Save() { return {}; }
function NorProbeMain::Load(version, data) {}
