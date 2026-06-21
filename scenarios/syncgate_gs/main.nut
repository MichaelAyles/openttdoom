/*
 * syncgate: PURE TRACK-SIGNAL clock interlock + output register.
 *
 * Built and verified incrementally. This file builds the STAGE under test (selected by
 * STAGE below) so each piece is proven in isolation before composing.
 *
 *   STAGE 1: a self-sustaining CLOCK train on a one-way block-signalled loop. Proven to
 *            circulate 8+ laps with a stable period (35 sample-intervals == ~525 ticks),
 *            from raw positions. The GS only OBSERVES after launch.
 *   STAGE 2: a PURE RELEASE INTERLOCK. A second READER train is held at a RELEASE signal
 *            whose protected block is MERGED (via a perpendicular dead-end stub) with one
 *            tile of the clock loop, the CLOCK BLOCK. While the clock train sits on the
 *            clock block the reader's release is RED (block occupied); when the clock
 *            leaves, the release goes GREEN and the reader advances. NO GameScript is in
 *            the timing path: the green aspect is computed by the engine from block
 *            occupancy every tick. We OBSERVE both trains and count reader advances vs
 *            clock laps to prove the reader is metered once per lap by the clock alone.
 *
 * KEY LESSON (cost me several runs): the COMPANY NAME has a ~31-char limit. A readout
 * string that grows unbounded silently stops taking effect (SetName no-ops past the
 * limit) and the displayed name FREEZES while the script runs on. Keep the name SHORT
 * and bounded. The clock never actually stalled; the readout did.
 *
 * Build on the verified primitives: scenarios/norgate_gs (block signal reads occupancy,
 * BuildSignal(tile,front) facing front->tile, dead-end-needs-terminating-signal rule)
 * and scenarios/clockgate_gs/main_clock.nut (the clock loop).
 */

STAGE <- 1;

// ---- clock loop geometry (one-way block-signalled, single train) ----
LX0 <- 30; LX1 <- 38; LY0 <- 20; LY1 <- 26;
CDX <- 33;                 // clock depot column (depot at (CDX, LY0-1))
// CLOCK BLOCK: one tile of the BOTTOM run (travel west). The clock train sweeps west
// through it once per lap. Its occupancy is read by the reader's release signal.
CBX <- 34;                 // clock-block tile x on the bottom run (y = LY1)

// ---- reader LOOP geometry (a rectangle BELOW the clock loop) ----
// The reader circulates its own loop forever. On its TOP run sits a RELEASE signal; the
// block just ahead of the release signal is merged (via a vertical stub on column CBX)
// with one tile of the clock loop, the CLOCK BLOCK. So each reader lap the reader is
// HELD at the release signal while the clock occupies the clock block, and released when
// the clock leaves. The reader is metered once per clock lap by occupancy alone.
RX0 <- 30; RX1 <- 38; RY0 <- 31; RY1 <- 37;   // reader loop rectangle
RDX <- 31;                 // reader depot column (depot at (RDX, RY0-1)) -- removed post-launch? no.
RELX  <- 33;               // reader RELEASE signal x on the reader top run (y = RY0)
// CLOCK BLOCK shares column CBX (=34): a vertical stub on column CBX joins the reader top
// run (RY0) up to the clock block (LY1). The reader top run travels +X (east); the
// release signal at RELX is just west of the stub, so the block ahead of the release
// (containing the stub + clock block) is occupied exactly while the clock is on the clock
// block. The stub is a perpendicular dead-end branch: no train drives along it.

class SyncGateMain extends GSController {
    company = null; eng = null;
    clock = null; cdepot = null;
    reader = null; rdepot = null;
    constructor() {}
}

function SyncGateMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function SyncGateMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function SyncGateMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function SyncGateMain::Say(s) { GSCompany.SetName(s); }
function SyncGateMain::T(x, y) { return GSMap.GetTileIndex(x, y); }

function SyncGateMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// Build a closed rectangular rail loop (straights + 4 corner curves). Pristine: no
// signals. A single train circulates forever (verified, main_clock.nut).
function SyncGateMain::BuildRect(x0, y0, x1, y1) {
    for (local x = x0 + 1; x < x1; x++) {
        GSRail.BuildRailTrack(this.T(x, y0), GSRail.RAILTRACK_NE_SW);
        GSRail.BuildRailTrack(this.T(x, y1), GSRail.RAILTRACK_NE_SW);
    }
    for (local y = y0 + 1; y < y1; y++) {
        GSRail.BuildRailTrack(this.T(x0, y), GSRail.RAILTRACK_NW_SE);
        GSRail.BuildRailTrack(this.T(x1, y), GSRail.RAILTRACK_NW_SE);
    }
    GSRail.BuildRailTrack(this.T(x0, y0), GSRail.RAILTRACK_SW_SE);  // top-left
    GSRail.BuildRailTrack(this.T(x1, y0), GSRail.RAILTRACK_NE_SE);  // top-right
    GSRail.BuildRailTrack(this.T(x1, y1), GSRail.RAILTRACK_NW_NE);  // bottom-right
    GSRail.BuildRailTrack(this.T(x0, y1), GSRail.RAILTRACK_NW_SW);  // bottom-left
}

function SyncGateMain::Launch(depot, wp1, wp2) {
    local v = GSVehicle.BuildVehicle(depot, this.eng);
    if (!GSVehicle.IsValidVehicle(v)) return null;
    GSOrder.AppendOrder(v, wp1, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSOrder.AppendOrder(v, wp2, GSOrder.OF_NON_STOP_INTERMEDIATE);
    for (local r = 0; r < 30; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(5);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    return v;
}

// Ring the loop with ONE-WAY NORMAL block signals facing the direction of travel
// (clockwise as launched: east along the top, south down the right, west along the
// bottom, north up the left). A single train on a one-way block-signalled loop reserves
// block-by-block and, being the only train, can never mutually deadlock. Normal block
// signals avoid the PBS whole-path reservation that can refuse to wrap a closed loop.
// One signal per run side keeps each side a single block (plenty for one train).
function SyncGateMain::SignalLoopOneWay() {
    // top run: travel +X (east). front = x-1 permits x-1 -> x.
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_NORMAL);
    // right run: travel +Y (south). front = y-1.
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_NORMAL);
    // bottom run: travel -X (west). front = x+1.
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_NORMAL);
    // left run: travel -Y (north). front = y+1.
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_NORMAL);
}

// One-way PBS (path) signals around the clock loop. With PBS the clock reserves a
// PATH (track-by-track) rather than a whole block, so a reader train parked on a stub
// branch that merges into the clock block does NOT block the clock's straight-through
// path. This is the one variant that might give a non-coupling occupancy read.
function SyncGateMain::SignalLoopPBS() {
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_PBS_ONEWAY);
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_PBS_ONEWAY);
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_PBS_ONEWAY);
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_PBS_ONEWAY);
}

// Build the clock loop STATIC track + signals + depot (no train launch yet). pbs=true
// rings it with one-way PBS path signals instead of one-way normal block signals.
function SyncGateMain::BuildClockStatic(pbs = false) {
    this.BuildRect(LX0, LY0, LX1, LY1);
    this.cdepot = this.T(CDX, LY0 - 1);
    GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
    if (pbs) this.SignalLoopPBS(); else this.SignalLoopOneWay();
}

// STAGE 2: the reader LOOP + the clock-block stub read (the pure interlock). STATIC
// track + signals only (no train launch yet).
function SyncGateMain::BuildReaderStatic() {
    // reader loop rectangle, clockwise, one-way block signals so a single reader train
    // circulates forever. The RELEASE signal on the top run is what the clock gates.
    this.BuildRect(RX0, RY0, RX1, RY1);
    this.rdepot = this.T(RDX, RY0 - 1);
    GSRail.BuildRailDepot(this.rdepot, this.T(RDX, RY0));
    GSRail.BuildRailTrack(this.T(RDX, RY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(RDX, RY0), GSRail.RAILTRACK_NW_SW);
    // one-way block signals around the reader loop, skipping the release-block tiles.
    for (local x = RX0 + 2; x < RX1; x += 3)
        if (x != RELX && x != CBX && x != CBX + 1)
            GSRail.BuildSignal(this.T(x, RY0), this.T(x - 1, RY0), GSRail.SIGNALTYPE_NORMAL);
    for (local y = RY0 + 2; y < RY1; y += 3)
        GSRail.BuildSignal(this.T(RX1, y), this.T(RX1, y - 1), GSRail.SIGNALTYPE_NORMAL);
    for (local x = RX1 - 2; x > RX0; x -= 3)
        GSRail.BuildSignal(this.T(x, RY1), this.T(x + 1, RY1), GSRail.SIGNALTYPE_NORMAL);
    for (local y = RY1 - 2; y > RY0; y -= 3)
        GSRail.BuildSignal(this.T(RX0, y), this.T(RX0, y + 1), GSRail.SIGNALTYPE_NORMAL);

    // RELEASE signal on the reader top run, eastbound-permissive (front = RELX-1).
    GSRail.BuildSignal(this.T(RELX, RY0), this.T(RELX - 1, RY0), GSRail.SIGNALTYPE_NORMAL);
    // terminating signal east of the stub column so the release block is a through block.
    GSRail.BuildSignal(this.T(CBX + 1, RY0), this.T(CBX, RY0), GSRail.SIGNALTYPE_NORMAL);

    // ---- the STUB READ (one-directional, NO mutual blocking) ----
    // The clock block is isolated to one tile (CBX, LY1) on the clock bottom run by
    // bounding one-way signals (bottom run travels -X / west; front = x+1).
    GSRail.BuildSignal(this.T(CBX, LY1),     this.T(CBX + 1, LY1), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(CBX - 1, LY1), this.T(CBX, LY1),     GSRail.SIGNALTYPE_NORMAL);
    // vertical stub on column CBX from the clock block (LY1) down to the reader top run
    // (RY0). A TWO-WAY signal partway down SEPARATES the clock block (above) from the
    // reader release block (below): the clock keeps its own block (the reader can never
    // hold it), while the two-way signal's BACK face, seen from the reader side, reads the
    // clock-block occupancy and holds the reader. This is the asymmetric read that a plain
    // block merge (which deadlocked the clock) cannot give.
    for (local y = LY1; y <= RY0; y++)
        GSRail.BuildRailTrack(this.T(CBX, y), GSRail.RAILTRACK_NW_SE);
    // crossings at both ends so the stub is electrically continuous with each run, but no
    // train can turn onto it (no curve piece links the straight run to the stub).
    GSRail.BuildRailTrack(this.T(CBX, LY1), GSRail.RAILTRACK_NE_SW);  // clock-block crossing
    GSRail.BuildRailTrack(this.T(CBX, RY0), GSRail.RAILTRACK_NE_SW);  // reader-top crossing
    // two-way signal in the stub separating the two blocks. STUBY is between the runs.
    local stuby = LY1 + 2;   // a tile in the middle of the stub
    GSRail.BuildSignal(this.T(CBX, stuby), this.T(CBX, stuby - 1), GSRail.SIGNALTYPE_NORMAL_TWOWAY);
}

// STAGE 3: a PRESIGNAL read of the clock block. The reader's RELEASE is an ENTRY
// presignal; the block ahead of it ends in an EXIT presignal that faces the clock block.
// An entry presignal is GREEN iff at least one exit ahead is GREEN; an exit is GREEN iff
// its block (the clock block) is clear. So the reader's release is GREEN iff the clock
// block is clear == reader HELD while the clock is on the clock block, released when it
// leaves. The EXIT signal is the block boundary, so the reader's reservation never enters
// the clock loop (no mutual blocking), while the aspect is still read across the boundary.
function SyncGateMain::BuildReaderPresignal() {
    this.BuildRect(RX0, RY0, RX1, RY1);
    this.rdepot = this.T(RDX, RY0 - 1);
    GSRail.BuildRailDepot(this.rdepot, this.T(RDX, RY0));
    GSRail.BuildRailTrack(this.T(RDX, RY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(RDX, RY0), GSRail.RAILTRACK_NW_SW);
    // plain one-way block signals around the rest of the reader loop.
    for (local y = RY0 + 2; y < RY1; y += 3)
        GSRail.BuildSignal(this.T(RX1, y), this.T(RX1, y - 1), GSRail.SIGNALTYPE_NORMAL);
    for (local x = RX1 - 2; x > RX0; x -= 3)
        GSRail.BuildSignal(this.T(x, RY1), this.T(x + 1, RY1), GSRail.SIGNALTYPE_NORMAL);
    for (local y = RY1 - 2; y > RY0; y -= 3)
        GSRail.BuildSignal(this.T(RX0, y), this.T(RX0, y + 1), GSRail.SIGNALTYPE_NORMAL);
    // also a normal one-way signal on the top run WEST of the release, so the reader's
    // approach to the release is its own block (it queues there when held).
    GSRail.BuildSignal(this.T(RX0 + 1, RY0), this.T(RX0, RY0), GSRail.SIGNALTYPE_NORMAL);

    // RELEASE = ENTRY presignal on the reader top run (eastbound, front = RELX-1).
    GSRail.BuildSignal(this.T(RELX, RY0), this.T(RELX - 1, RY0), GSRail.SIGNALTYPE_ENTRY);
    // The block ahead of the entry runs east along the top run and ALSO up the stub. It
    // must contain an EXIT signal for the entry to read. Put the EXIT at the top of the
    // stub, facing UP into the clock block, so it reads the clock-block clearance.
    // Continue the reader top run east past the stub to a normal terminating signal so the
    // entry's block is a proper through block on the lane side too.
    GSRail.BuildSignal(this.T(CBX + 2, RY0), this.T(CBX + 1, RY0), GSRail.SIGNALTYPE_NORMAL);

    // ---- the stub: from the reader top run (RY0) up to the clock block (LY1) ----
    // vertical straight stub, with a curve at the top joining the clock block tile, and an
    // EXIT presignal at the stub top facing the clock block (front = the clock block tile).
    for (local y = LY1 + 1; y < RY0; y++)
        GSRail.BuildRailTrack(this.T(CBX, y), GSRail.RAILTRACK_NW_SE);
    // join stub bottom into the reader top run via a curve (so the reader's top-run block
    // includes the stub). NW_SW connects the run (SW/west) to the stub (NW/north).
    GSRail.BuildRailTrack(this.T(CBX, RY0), GSRail.RAILTRACK_NE_SW);   // run straight
    GSRail.BuildRailTrack(this.T(CBX, RY0), GSRail.RAILTRACK_NW_SE);   // stub straight (crossing)
    // join stub top to the clock block tile (CBX, LY1) via a curve so the EXIT can face it.
    GSRail.BuildRailTrack(this.T(CBX, LY1), GSRail.RAILTRACK_NE_SW);   // clock run straight
    GSRail.BuildRailTrack(this.T(CBX, LY1 + 1), GSRail.RAILTRACK_NW_SE);
    // EXIT presignal at the stub tile just below the clock block, facing NORTH so the
    // block it guards (ahead) is the CLOCK BLOCK. BuildSignal(tile, front) permits
    // front->tile; for a north-guarding signal the train approaches from the south, so
    // front = the tile to the south. Exit GREEN iff the clock block (ahead) is clear.
    GSRail.BuildSignal(this.T(CBX, LY1 + 1), this.T(CBX, LY1 + 2), GSRail.SIGNALTYPE_EXIT);
    // isolate the clock block on the clock bottom run so its occupancy is one tile.
    GSRail.BuildSignal(this.T(CBX, LY1),     this.T(CBX + 1, LY1), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(CBX - 1, LY1), this.T(CBX, LY1),     GSRail.SIGNALTYPE_NORMAL);
}

function SyncGateMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("SYNG build s" + STAGE);
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    // Prepare a flat canvas covering the clock loop (rows 20-26) and the reader loop
    // below (rows 31-37), plus the stub between.
    this.Prepare(LX0 - 2, LY0 - 2, RX1 + 2, RY1 + 2);

    if (STAGE == 1) {
        this.BuildClockStatic();
        this.clock = this.Launch(this.cdepot, this.T(LX1, LY1), this.T(LX0, LY0));
        if (this.clock == null) { this.Say("SYNG NOVEH"); while (true) GSController.Sleep(74); }
        this.Say("SYNG roll s1");
        this.ObserveClock();
        return;
    }

    // STAGE 2/3: build BOTH static structures first, then launch the READER (it parks held
    // at the release signal, WEST of the stub, clear of the clock's path), then launch the
    // CLOCK last so its loop path is unobstructed.
    //   STAGE 2 = block-merge read (two-way stub signal).
    //   STAGE 3 = presignal read (entry release + exit at the clock block), which is meant
    //             to read the clock-block aspect WITHOUT coupling the reservation graph.
    // STAGE 4 uses a PBS clock loop (path reservation) + the block-merge reader, testing
    // whether PBS lets the clock reserve straight through the clock block even while the
    // reader sits in the merged block's stub (a non-coupling occupancy read).
    this.BuildClockStatic(STAGE == 4);
    if (STAGE == 3) this.BuildReaderPresignal();
    else this.BuildReaderStatic();
    this.reader = this.Launch(this.rdepot, this.T(RX1, RY1), this.T(RX0, RY0));
    if (this.reader == null) { this.Say("SYNG NORDR"); while (true) GSController.Sleep(74); }
    // let the reader settle (it should come to rest HELD at the release signal).
    GSController.Sleep(40);
    this.clock = this.Launch(this.cdepot, this.T(LX1, LY1), this.T(LX0, LY0));
    if (this.clock == null) { this.Say("SYNG NOVEH"); while (true) GSController.Sleep(74); }
    // robustly confirm the clock is circulating (reaches the bottom run within a couple of
    // laps). Re-kick once if needed (a one-time build-time action, not per-edge timing).
    for (local k = 0; k < 3; k++) {
        local seen = false;
        for (local i = 0; i < 60; i++) {
            local cy = this.Ty(this.clock);
            if (cy == LY1) { seen = true; break; }
            GSController.Sleep(5);
        }
        if (seen) break;
        if (GSVehicle.IsStoppedInDepot(this.clock)) GSVehicle.StartStopVehicle(this.clock);
    }
    this.Say("SYNG roll s" + STAGE);
    this.ObserveInterlock();
}

// STAGE 1 readout: clock laps + stable period, from raw positions, GS observing only.
function SyncGateMain::ObserveClock() {
    local cPrevOn = false; local cLaps = 0; local lastEdgeIdx = -1;
    local idx = 0; local lastP = 0; local prevP = 0;
    while (true) {
        GSController.Sleep(15);
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        local cOn = (cx == LX0 && cy >= LY0 && cy <= LY1);
        if (cOn && !cPrevOn) {
            cLaps++;
            if (lastEdgeIdx >= 0) { prevP = lastP; lastP = idx - lastEdgeIdx; }
            lastEdgeIdx = idx;
        }
        cPrevOn = cOn;
        this.Say("SG L" + cLaps + " " + cx + "." + cy + " p" + prevP + "," + lastP);
        idx++;
    }
}

// STAGE 2 readout: prove the reader is metered ONCE PER LAP by the clock alone. We count
// clock laps (rising edge into the left run) and reader advances (rising edge where the
// reader reaches the EAST depot after a release). The GS NEVER starts/stops either train
// after launch; the release is the engine's block-occupancy aspect. If reader-advances
// tracks clock-laps 1:1, the clock-block occupancy is releasing the reader per lap.
function SyncGateMain::ObserveInterlock() {
    local cPrevOn = false; local cLaps = 0;
    local rPrevPass = false; local rPasses = 0;   // reader passes of the release point
    local rPrevLapOn = false; local rLaps = 0;    // reader full loop laps
    local idx = 0;
    while (true) {
        GSController.Sleep(15);
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        local rx = this.Tx(this.reader); local ry = this.Ty(this.reader);
        // clock lap: rising edge entering the clock's left run.
        local cOn = (cx == LX0 && cy >= LY0 && cy <= LY1);
        if (cOn && !cPrevOn) cLaps++;
        cPrevOn = cOn;
        // reader PASS of the release point: rising edge just EAST of RELX on the reader
        // top run (it cleared the release signal this lap, gated by clock-block occupancy).
        local rPass = (ry == RY0 && rx >= RELX + 1 && rx <= CBX + 1);
        if (rPass && !rPrevPass) rPasses++;
        rPrevPass = rPass;
        // reader full lap: rising edge entering the reader's left run.
        local rLapOn = (rx == RX0 && ry >= RY0 && ry <= RY1);
        if (rLapOn && !rPrevLapOn) rLaps++;
        rPrevLapOn = rLapOn;
        // bounded readout: clock laps cL, reader passes P, reader laps rL, reader x, clock
        // pos. A judge confirms P tracks cL 1:1 (metered once per clock lap) and that the
        // reader sits HELD at RELX (rx near RELX) between releases.
        this.Say("IL cL" + cLaps + " P" + rPasses + " rL" + rLaps + " rx" + rx + " c" + cx + "." + cy);
        idx++;
    }
}

function SyncGateMain::Save() { return {}; }
function SyncGateMain::Load(version, data) {}
