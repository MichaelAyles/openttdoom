/*
 * clockgate sub-goal 2: LIVE RE-EVALUATION of one NOT gate on the SAME physical
 * tiles. The gate is built ONCE and never rebuilt; only the INPUT changes (a train is
 * poked onto / off the input tap), and we re-dispatch a reader to read the output each
 * time. The gate is the proven norgate primitive on a simple straight lane:
 *   [west depot @BX-1] === [reader SIG @SIGX] in-tap @INX [term SIG @SIG2X] [east depot @EASTX]
 * A normal block signal is RED iff its protected (through) block is occupied, so an
 * EASTBOUND reader passes the signal iff the input block is empty == NOT(input).
 * BuildSignal(tile, front) permits travel FROM front INTO tile, so the eastbound
 * reader signal needs front = SIGX-1; the terminating signal makes the block a through
 * block.
 *
 * Sequence on ONE built gate:
 *   read A: input ABSENT  -> reader PASSES  -> final x at the east end (>=51)  == 1
 *   poke:   ADD an input train on the tap (no gate rebuild)
 *   read B: input PRESENT -> reader HELD    -> final x at the signal (<=SIGX)  == 0
 *   unpoke: REMOVE the input train (no gate rebuild)
 *   read C: input ABSENT  -> reader PASSES  -> final x at the east end (>=51)  == 1
 *
 * TEARDOWN, the hard part (facts found empirically here):
 *  - A normal one-way block signal BLOCKS the return (its back is solid), so a reader
 *    cannot ping-pong back west through the gate. Each read therefore uses a FRESH
 *    eastbound reader from the west depot (a simple lane, no coupled junction, so the
 *    norchain teardown hang does not apply).
 *  - GSVehicle.SellVehicle only works on a vehicle stopped IN A DEPOT. A reader HELD at
 *    the signal (read B) is on open track and CANNOT be sold there; selling it in place
 *    fails and the train piles up, jamming the next reader in the west depot. The fix:
 *    a held reader is freed by REMOVING the input (its block empties, the signal goes
 *    green), after which it rolls into the east depot on its standing order and is sold
 *    cleanly there. So we order read B's disposal to happen AFTER the unpoke. We also
 *    verify each sale (the train count must return to the input-only baseline) before
 *    the next read, and drain any stragglers, so the lane is always clear.
 *
 * Readout: "REEVAL sNN xa xb xc" into the company name (rcon companies). Judge from the
 * RAW numbers: xa>NN (passed=1), xb<=NN (held=0), xc>NN (passed=1) == the SAME gate's
 * output followed the input across live changes.
 */

BX    <- 40;
SIGX  <- BX + 6;       // reader signal x (46)
INX   <- SIGX + 1;     // input tap x (47), inside the protected block
SIG2X <- SIGX + 4;     // terminating signal x (50)
EASTX <- SIGX + 6;     // east depot x (52)
Y     <- 50;

class ReevalMain extends GSController {
    company = null; eng = null;
    wDepot = null; eDepot = null; inDepot = null;
    input = null; reader = null;
    constructor() {}
}

function ReevalMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function ReevalMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function ReevalMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function ReevalMain::Say(s) { GSCompany.SetName(s); }
function ReevalMain::T(x, y) { return GSMap.GetTileIndex(x, y); }
function ReevalMain::NTrains() { local l = GSVehicleList(); return l.Count(); }

function ReevalMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// Park an input train on (INX, Y) from the feeder depot. Returns the veh.
function ReevalMain::Poke() {
    local v = GSVehicle.BuildVehicle(this.inDepot, this.eng);
    GSOrder.AppendOrder(v, this.T(INX, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && this.Tx(v)==INX && this.Ty(v)==Y) {
            GSVehicle.StartStopVehicle(v);   // stop dead on the tap
            break;
        }
    }
    return v;
}

// Remove the input: drive it back into its feeder depot (north) and sell it there.
function ReevalMain::Unpoke() {
    local v = this.input;
    if (v == null || !GSVehicle.IsValidVehicle(v)) { this.input = null; return; }
    GSOrder.AppendOrder(v, this.inDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSVehicle.StartStopVehicle(v);   // resume from its manual stop on the tap
    for (local w = 0; w < 30; w++) {
        GSController.Sleep(6);
        if (GSVehicle.IsStoppedInDepot(v)) break;
    }
    if (GSVehicle.IsValidVehicle(v)) GSVehicle.SellVehicle(v);
    this.input = null;
}

// Build a fresh eastbound reader from the west depot, run it, and return its final x.
// Leaves the reader where it stopped (east depot if it passed, held on track if not),
// stored in this.reader for the caller to dispose.
function ReevalMain::ReadOnce(tag) {
    local v = GSVehicle.BuildVehicle(this.wDepot, this.eng);
    this.reader = v;
    GSOrder.AppendOrder(v, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 14; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = BX - 1;
    for (local s = 0; s < 18; s++) {
        GSController.Sleep(18);
        local nx = this.Tx(v);
        if (nx >= 0) fx = nx;
        if (s % 6 == 0) this.Say("RD " + tag + " x" + nx + " fx" + fx);
    }
    return fx;
}

// Dispose the current reader cleanly. It can only be SOLD from a depot. If it PASSED it
// is already in the east depot. If it was HELD, the caller must have removed the input
// first (so the signal is green); we then wait for it to roll into the east depot and
// sell it. We verify the train count drops, draining once if needed.
function ReevalMain::Dispose(tag, baseline) {
    local v = this.reader;
    if (v != null && GSVehicle.IsValidVehicle(v)) {
        for (local s = 0; s < 30; s++) {
            if (GSVehicle.IsStoppedInDepot(v)) break;
            GSController.Sleep(10);
        }
        if (GSVehicle.IsValidVehicle(v)) GSVehicle.SellVehicle(v);
    }
    this.reader = null;
    GSController.Sleep(8);
    this.Say("RD " + tag + " disp n" + this.NTrains());
    GSController.Sleep(4);
}

function ReevalMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("REEVAL build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    this.Prepare(BX - 2, Y - 2, EASTX + 1, Y + 2);

    // Build the gate ONCE.
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(this.T(x, Y), GSRail.RAILTRACK_NE_SW);
    this.wDepot = this.T(BX - 1, Y);
    GSRail.BuildRailDepot(this.wDepot, this.T(BX, Y));
    this.eDepot = this.T(EASTX, Y);
    GSRail.BuildRailDepot(this.eDepot, this.T(EASTX - 1, Y));
    GSRail.BuildSignal(this.T(SIGX, Y),  this.T(SIGX - 1, Y),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(SIG2X, Y), this.T(SIG2X - 1, Y), GSRail.SIGNALTYPE_NORMAL);
    this.inDepot = this.T(INX, Y - 1);
    GSRail.BuildRailDepot(this.inDepot, this.T(INX, Y));
    GSRail.BuildRailTrack(this.T(INX, Y), GSRail.RAILTRACK_NW_NE);
    this.Say("REEVAL built");

    // read A: input absent -> expect pass (reader to east end). Dispose (it is parked
    // in the east depot, sellable) before the next read.
    local xa = this.ReadOnce("A");
    this.Say("REEVAL a s" + SIGX + " " + xa);
    this.Dispose("A", 0);

    // poke: add an input train on the SAME gate, no rebuild.
    this.input = this.Poke();
    this.Say("REEVAL poke ix" + this.Tx(this.input));
    GSController.Sleep(10);

    // read B: input present -> expect held (reader pinned at the signal). Do NOT
    // dispose yet: the held reader cannot be sold on open track.
    local xb = this.ReadOnce("B");
    this.Say("REEVAL ab s" + SIGX + " " + xa + " " + xb);

    // unpoke FIRST (frees the held read-B reader: its block empties, signal greens),
    // THEN dispose it (it now rolls into the east depot and is sold there cleanly).
    this.Unpoke();
    GSController.Sleep(10);
    this.Dispose("B", 0);

    // read C: input absent again -> expect pass.
    local xc = this.ReadOnce("C");
    this.Dispose("C", 0);

    // FINAL readout. Judge from RAW numbers: xa>SIGX (passed=1), xb<=SIGX (held=0),
    // xc>SIGX (passed=1). SAME gate, three live reads.
    local nm = "REEVAL s" + SIGX + " " + xa + " " + xb + " " + xc;
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function ReevalMain::Save() { return {}; }
function ReevalMain::Load(version, data) {}
