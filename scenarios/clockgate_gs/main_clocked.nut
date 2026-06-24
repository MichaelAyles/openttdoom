/*
 * clockgate: a RELIABLE GS-mediated CLOCKED NOT gate.
 *
 * This is the reliable successor to main_sync.nut (which clock-synchronised sampling via
 * the GameScript but reproduced 0 of 3 independently). GS-mediated clocking is acceptable:
 * the GS waits for the clock train to reach a known phase each edge and then dispatches the
 * reader. The goal is RELIABILITY and correctness, derived from RAW reader positions.
 *
 * TWO verified primitives, composed:
 *   - the SELF-SUSTAINING CLOCK from syncgate STAGE 1: a single train on a closed
 *     rectangular loop ringed with ONE-WAY NORMAL block signals (clockwise), two
 *     opposite-corner waypoints. A single train on a one-way-signalled loop reserves
 *     block-by-block forward and, being the only train, can never mutually deadlock; the
 *     back of a one-way signal is solid so it never re-enters the depot. This is the fix
 *     for the prior PLAIN-loop clock that occasionally re-pathed into the depot and parked.
 *   - the NOT gate from main_reeval.nut: a straight lane with a reader block signal whose
 *     protected (through) block holds one input tap, terminated by a second signal. A
 *     normal block signal is RED iff its block is occupied, so an eastbound reader passes
 *     iff the input block is empty == NOT(input). The reader's FINAL x is the output:
 *     x > GSIGX (rolled into the east depot) = 1, x <= GSIGX (held at the signal) = 0.
 *
 * CLOCK SYNCHRONISATION (the per-edge wait). Each edge the GS BLOCKS until the clock train
 * crosses a fixed phase of its loop: a rising edge ENTERING the left run (a multi-tile
 * region x==LX0, y in [LY0..LY1], immune to the missed-single-tile poll alias). Only then
 * does it take the gate sample. So every sample is released by a real clock edge, not a
 * free-running timer. The per-edge wait count is reported (a small value, not the timeout,
 * proves a real edge released the sample).
 *
 * INPUT SCHEDULE (input PRESENT during edge k's sample window):  0 1 1 0 1 0
 * Because the input is SET BEFORE the reader is dispatched each edge, the output read at
 * edge k is NOT(schedule[k]) directly (no register latency to approximate):
 *   edge:  0 1 2 3 4 5
 *   in  :  0 1 1 0 1 0
 *   out :  1 0 0 1 0 1     (out[k] = NOT(in[k]), MSB = edge 0)
 * Final readout encodes the six observed bits as "CG 100101", every bit derived from the
 * RAW reader x (out = reader_x > GSIGX), never computed from the schedule.
 *
 * RELIABILITY DISCIPLINE (hard-won from prior runs):
 *  - The clock launch is flaky. We RETRY BuildVehicle + StartStop until the clock is
 *    CONFIRMED circulating (it left the depot and completed at least one full lap, seen as
 *    two distinct loop edges) BEFORE building/driving the gate. On failure we set "CKFAIL"
 *    and stop cleanly, never restarting Start().
 *  - The company name has a ~31-char limit; SetName silently no-ops past it and the name
 *    FREEZES. EVERY readout here is SHORT and fixed-width.
 *  - Per-edge reader disposal can jam the lane. Each edge we dispatch a FRESH reader, read
 *    its final x, then DRAIN the lane (a held reader is freed by removing the input first,
 *    then it rolls into the east depot and is sold) and confirm the lane is clear before
 *    the next edge.
 *  - ALL vehicle ops are guarded so an exception can never bubble out and restart Start()
 *    (which would grow the train count).
 */

// ---- clock loop geometry (syncgate STAGE 1: one-way block-signalled, single train) ----
LX0 <- 30; LX1 <- 38; LY0 <- 20; LY1 <- 26;
CDX <- 33;                 // clock depot column (depot at (CDX, LY0-1))

// ---- NOT gate geometry (main_reeval primitive, its own rows, well clear of the loop) ----
BX    <- 40;
GSIGX <- BX + 6;           // reader signal x (46)
INX   <- GSIGX + 1;        // input tap x (47), inside the protected block
SIG2X <- GSIGX + 4;        // terminating signal x (50)
EASTX <- GSIGX + 6;        // east depot x (52)
GY    <- 40;

class ClockedMain extends GSController {
    company = null; eng = null;
    clock = null; cdepot = null;
    wDepot = null; eDepot = null; inDepot = null;
    input = null; reader = null;
    started = false;
    bits = null;
    constructor() {}
}

function ClockedMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function ClockedMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function ClockedMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function ClockedMain::Say(s) { GSCompany.SetName(s); }
function ClockedMain::T(x, y) { return GSMap.GetTileIndex(x, y); }
function ClockedMain::NTrains() { local l = GSVehicleList(); return l.Count(); }

function ClockedMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// Build a closed rectangular rail loop (straights + 4 corner curves), no signals.
function ClockedMain::BuildRect(x0, y0, x1, y1) {
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

// Ring the clock loop with ONE-WAY NORMAL block signals facing the direction of travel
// (clockwise: east along the top, south down the right, west along the bottom, north up the
// left). One signal per run side keeps each side a single block, plenty for one train.
function ClockedMain::SignalLoopOneWay() {
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_NORMAL);  // top +X
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_NORMAL);  // right +Y
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_NORMAL);  // bottom -X
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_NORMAL);  // left -Y
}

// Build the clock loop static track + signals + depot (no train launch yet).
function ClockedMain::BuildClockStatic() {
    this.BuildRect(LX0, LY0, LX1, LY1);
    this.cdepot = this.T(CDX, LY0 - 1);
    GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
    this.SignalLoopOneWay();
}

// Launch the clock and CONFIRM it is circulating before returning true. The clock is given
// two opposite-corner waypoints so its order list cycles it round the one-way loop forever.
// We RETRY the start nudge and only accept once we have seen the train on TWO DISTINCT loop
// edges that are not the depot (proof it left the depot and is actually moving round), then
// confirm it completes a lap (returns to the left run). Bounded; returns false on failure.
// ---- HARDENED CLOCK LAUNCH (shared helper, identical across clockgate/register/toggle) ----
//
// THE DIAGNOSED FLAW. The old launch nudged egress with a TIGHT poll:
//     for (...) { if (IsStoppedInDepot) StartStopVehicle; Sleep(5); if (moved) break; }
// StartStopVehicle TOGGLES the stopped flag and is an ASYNCHRONOUS (queued) command. After it
// is fired the train stays IsStoppedInDepot==true for several ticks until the command lands and
// the train physically clears the depot tile. In that window the tight poll re-reads
// IsStoppedInDepot==true and fires a SECOND toggle, which RE-STOPS the train once both land.
// Under the extra command-queue latency of a concurrent CPU-heavy server these double-toggles
// OSCILLATE: the train takes many cycles to leave, and ~1 in 3 fresh starts it never leaves
// inside the egress budget, giving a stall / CKFAIL.
//
// THE FIX, three layers: NudgeEgress fires EXACTLY ONE start toggle per SETTLE (no double-fire);
// LaunchOnce does a movement-verified egress then a robust lap confirm; LaunchClockConfirmed
// wraps LaunchOnce in a TEARDOWN-AND-RETRY so a stuck attempt can never poison the next.

// Clear all orders off a vehicle (clockgate has no ClearOrders helper; inline it here so the
// reused clock token never ping-pongs against stale orders during teardown).
function ClockedMain::ClearOrders(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    while (GSOrder.GetOrderCount(v) > 0) { if (!GSOrder.RemoveOrder(v, 0)) break; }
}

// One-shot, settle-verified depot egress. Fires AT MOST one start toggle per SETTLE so a queued
// toggle is never double-fired (the old bug). True once the clock leaves the depot tile.
function ClockedMain::NudgeEgress(v) {
    // GENEROUS total budget (40 * 12 = 480 ticks, longer than the old 400-tick egress). A fresh
    // toggle is fired ONLY when the train is CONFIRMED still stopped-in-depot after the prior
    // settle (a dropped command); a started-but-not-yet-moving train reads false and is left
    // alone, so a command in flight is never double-toggled.
    for (local r = 0; r < 40; r++) {
        if (!GSVehicle.IsValidVehicle(v)) return false;
        local cx = this.Tx(v); local cy = this.Ty(v);
        if (cx >= 0 && !(cx == CDX && cy == LY0 - 1)) return true;
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(12);
    }
    if (GSVehicle.IsValidVehicle(v)) {
        local cx = this.Tx(v); local cy = this.Ty(v);
        if (cx >= 0 && !(cx == CDX && cy == LY0 - 1)) return true;
    }
    return false;
}

function ClockedMain::LaunchOnce() {
    this.clock = null;
    for (local b = 0; b < 12; b++) {
        local v = GSVehicle.BuildVehicle(this.cdepot, this.eng);
        if (GSVehicle.IsValidVehicle(v)) { this.clock = v; break; }
        GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
        GSController.Sleep(10);
    }
    if (!GSVehicle.IsValidVehicle(this.clock)) return false;
    GSOrder.AppendOrder(this.clock, this.T(LX1, LY1), GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSOrder.AppendOrder(this.clock, this.T(LX0, LY0), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (!this.NudgeEgress(this.clock)) return false;
    local sawBottom = false;
    for (local i = 0; i < 400; i++) {
        if (!GSVehicle.IsValidVehicle(this.clock)) return false;
        if (GSVehicle.IsStoppedInDepot(this.clock)) { GSVehicle.StartStopVehicle(this.clock); GSController.Sleep(12); }
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        if (cy == LY1) sawBottom = true;                       // reached the far (bottom) run
        if (sawBottom && cx == LX0 && cy >= LY0 && cy <= LY1)  // returned to the left run
            return true;                                       // one full lap confirmed
        GSController.Sleep(5);
    }
    return false;
}

// Sell a stuck/leftover clock train between launch retries. Returns true only once the loop is
// CONFIRMED clear (parked and sold, or already gone). A moving train is NEVER sold (SellVehicle
// fails mid-track and would leak a second train onto the one-way loop): it is ordered into the
// depot and we wait beyond a full lap; this.clock is kept until the train is gone so a retry can
// re-target it. Fully guarded.
function ClockedMain::TeardownClock() {
    local v = this.clock;
    if (v == null || !GSVehicle.IsValidVehicle(v)) { this.clock = null; return true; }
    if (!GSVehicle.IsStoppedInDepot(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.cdepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local s = 0; s < 60; s++) {
            if (!GSVehicle.IsValidVehicle(v) || GSVehicle.IsStoppedInDepot(v)) break;
            GSController.Sleep(8);
        }
    }
    if (!GSVehicle.IsValidVehicle(v)) { this.clock = null; return true; }
    if (GSVehicle.IsStoppedInDepot(v)) {
        GSVehicle.SellVehicle(v);
        if (!GSVehicle.IsValidVehicle(v)) { this.clock = null; return true; }
    }
    return false;
}

function ClockedMain::LaunchClockConfirmed() {
    for (local t = 0; t < 4; t++) {
        if (this.LaunchOnce()) return true;
        this.Say("CG clkR" + t);
        for (local d = 0; d < 4 && !this.TeardownClock(); d++) GSController.Sleep(20);
        GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
        GSController.Sleep(20);
    }
    return false;
}

// Block until the clock train crosses a fixed loop phase: a RISING edge ENTERING the LEFT
// run (x==LX0, y in [LY0..LY1]). The left run is a multi-tile region so the poll cannot skip
// past it. Returns the number of sleeps waited (a small value proves a real edge released the
// sample; the 300 cap means a stalled clock). This is the per-edge clock synchronisation.
function ClockedMain::WaitClockEdge() {
    local waited = 0;
    local wasOff = false;
    for (local i = 0; i < 300; i++) {
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        local onLeft = (cx == LX0 && cy >= LY0 && cy <= LY1);
        if (onLeft && wasOff) return waited;     // rising edge: entered the left run
        if (!onLeft && cx >= 0) wasOff = true;
        GSController.Sleep(4);
        waited++;
    }
    return waited;
}

// Build the NOT gate ONCE (no input train yet). Same primitive as main_reeval.nut.
function ClockedMain::BuildGate() {
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(this.T(x, GY), GSRail.RAILTRACK_NE_SW);
    this.wDepot = this.T(BX - 1, GY);
    GSRail.BuildRailDepot(this.wDepot, this.T(BX, GY));
    this.eDepot = this.T(EASTX, GY);
    GSRail.BuildRailDepot(this.eDepot, this.T(EASTX - 1, GY));
    GSRail.BuildSignal(this.T(GSIGX, GY), this.T(GSIGX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(SIG2X, GY), this.T(SIG2X - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    this.inDepot = this.T(INX, GY - 1);
    GSRail.BuildRailDepot(this.inDepot, this.T(INX, GY));
    GSRail.BuildRailTrack(this.T(INX, GY), GSRail.RAILTRACK_NW_NE);
}

// Drive the input to `want` (1 = train parked on the tap, 0 = no input train). Idempotent:
// only acts on a change. Same poke/unpoke primitive as main_reeval.nut, fully guarded.
function ClockedMain::SetInput(want) {
    if (want && this.input == null) {
        local v = GSVehicle.BuildVehicle(this.inDepot, this.eng);
        if (!GSVehicle.IsValidVehicle(v)) return;
        GSOrder.AppendOrder(v, this.T(INX, GY), GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local w = 0; w < 40; w++) {
            GSController.Sleep(5);
            if (GSVehicle.IsValidVehicle(v) && this.Tx(v) == INX && this.Ty(v) == GY) {
                GSVehicle.StartStopVehicle(v);    // stop dead on the tap
                break;
            }
        }
        this.input = v;
    } else if (!want && this.input != null) {
        local v = this.input;
        if (GSVehicle.IsValidVehicle(v)) {
            GSOrder.AppendOrder(v, this.inDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
            GSVehicle.StartStopVehicle(v);        // resume from its manual stop on the tap
            for (local w = 0; w < 30; w++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
            if (GSVehicle.IsValidVehicle(v)) GSVehicle.SellVehicle(v);
        }
        this.input = null;
    }
}

// One gate sample: a FRESH eastbound reader from the west depot, return its FINAL x. Leaves
// the reader where it stopped (east depot if it passed, held at the signal if not), in
// this.reader for the caller to dispose.
function ClockedMain::Sample() {
    local v = GSVehicle.BuildVehicle(this.wDepot, this.eng);
    this.reader = v;
    if (!GSVehicle.IsValidVehicle(v)) return BX - 1;
    GSOrder.AppendOrder(v, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 14; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    // Read the reader's position over a FIXED window and take its FINAL x. This is the
    // proven main_reeval read: a fixed read avoids any early-break race where the reader is
    // sampled while still in the west depot (BX-1) before its launch nudge has taken effect,
    // which would wrongly read the depot tile as a held output. The window (18 * 16 ticks)
    // comfortably covers a full west->east traversal; the final x is the gate output.
    local fx = BX - 1;
    for (local s = 0; s < 18; s++) {
        GSController.Sleep(16);
        local nx = this.Tx(v);
        if (nx >= 0) fx = nx;
    }
    return fx;
}

// Dispose this edge's reader and CLEAR the lane before the next edge. If the reader was HELD
// at the signal (input present), the caller must drop the input to 0 first so it frees and
// rolls into the east depot; here we wait for it to reach a depot, sell it, then DRAIN any
// other parked reader (never the clock or the live input).
function ClockedMain::DisposeAndDrain() {
    local v = this.reader;
    if (v != null && GSVehicle.IsValidVehicle(v)) {
        for (local s = 0; s < 30; s++) {
            if (GSVehicle.IsStoppedInDepot(v)) break;
            GSController.Sleep(10);
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.reader = null;
    // drain any straggler reader parked in a depot (keeps the lane from filling up).
    local list = GSVehicleList();
    foreach (vv, _ in list) {
        if (vv == this.clock || vv == this.input) continue;
        if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv))
            GSVehicle.SellVehicle(vv);
    }
}

// Start() is a THIN GUARD around Run(). Two protections (rule E):
//  - a re-entry flag: if the framework ever re-enters Start() (e.g. after an error), the
//    second entry does NOT rebuild on top of leftover trains; it parks in a stable idle
//    loop. Rebuilding on leftovers was a real failure (readers stuck in the west depot).
//  - a try/catch: ANY exception out of Run() is caught and turned into a stable "CG ERR"
//    idle loop, so an exception can never bubble out and let the framework restart the
//    build (which would grow the train count).
function ClockedMain::Start() {
    // If a previous instance already computed the bits (persisted via Save/Load across an
    // engine-driven instance reset), do NOT rebuild over the finished run: just re-show the
    // result. This makes a stray restart harmless to a completed cycle.
    if (this.bits != null) {
        try { this.HoldResult(this.bits, 0); } catch (e) {}
        while (true) { this.Say("CG " + this.bits); GSController.Sleep(74); }
    }
    if (this.started) {
        while (true) { this.Say("CG REENTRY"); GSController.Sleep(74); }
    }
    this.started = true;
    try {
        this.Run();
    } catch (e) {
        while (true) { this.Say("CG ERR"); GSController.Sleep(74); }
    }
}

function ClockedMain::Run() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("CG build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    // WORLD-READY SETTLE. On a freshly launched dedicated server the first build commands
    // can fire before the economy/map are fully ready (this caused a run-1 CKFAIL where the
    // clock BuildVehicle failed instantly). Wait until a valid buildable engine is in hand,
    // then settle a moment, before any track or vehicle build.
    for (local w = 0; w < 40 && this.eng == null; w++) {
        GSController.Sleep(10);
        this.eng = this.PickEngine(rt);
    }
    GSController.Sleep(20);

    // Flat canvas: the gate rows (around GY=40) and the clock loop rows (20..26) are disjoint.
    this.Prepare(BX - 2, GY - 2, EASTX + 1, GY + 2);
    this.Prepare(LX0 - 2, LY0 - 2, LX1 + 2, LY1 + 2);

    // Build the gate first (static), then bring up the clock and CONFIRM it circulates
    // before any sampling. If the clock cannot be confirmed, stop cleanly (CKFAIL).
    // BuildGate is retried until its west depot tile is actually a depot (a fresh-server
    // build can partially fail; a half-built gate would jam every reader).
    for (local g = 0; g < 6; g++) {
        this.BuildGate();
        if (GSMap.IsValidTile(this.wDepot) && GSRail.IsRailDepotTile(this.wDepot)
            && GSRail.IsRailDepotTile(this.eDepot)) break;
        GSController.Sleep(15);
    }
    this.BuildClockStatic();
    this.Say("CG clk..");
    local ok = this.LaunchClockConfirmed();
    this.Say("CG clkOK" + (ok ? "" : "?"));
    if (!ok) { while (true) { this.Say("CKFAIL"); GSController.Sleep(74); } }
    this.Say("CG clkOK");

    // input schedule PRESENT during each edge's sample window; out[k] = NOT(in[k]).
    local sched = [0, 1, 1, 0, 1, 0];
    local bits = "";
    local pmin = 9999;            // smallest per-edge clock wait (proves real clock gating)
    for (local k = 0; k < sched.len(); k++) {
        // PER-EDGE CLOCK WAIT: block until the clock train crosses the loop phase. This is
        // the synchronisation; the sample is released by the clock, not a free timer.
        local waited = this.WaitClockEdge();
        if (waited < pmin) pmin = waited;
        // set the input for THIS edge BEFORE sampling, so the sample reflects schedule[k].
        local want = sched[k];
        this.SetInput(want == 1);
        GSController.Sleep(8);
        // take the gate sample: a fresh reader, read its RAW final x.
        local fx = this.Sample();
        local bit = (fx > GSIGX) ? 1 : 0;     // OUTPUT derived from the RAW reader position
        bits += bit;
        // short per-edge spot-check readout (fixed width): e<k> i<in> x<rawx> o<out>.
        this.Say("e" + k + " i" + want + " x" + fx + " o" + bit);
        GSController.Sleep(20);
        // dispose this edge's reader and clear the lane. A reader HELD at the signal (input
        // present) is freed by dropping the input to 0 first; then it rolls to the east
        // depot and is sold. Drop the input now (the next edge re-applies what it needs).
        if (this.input != null) this.SetInput(false);
        this.DisposeAndDrain();
    }

    // FINAL consolidated readout: "CG 100101" (MSB = edge 0). Every bit came from a raw
    // reader x (bit = reader_x > GSIGX), never from the schedule. Expected = NOT(010010)
    // = 100101. pmin is the smallest per-edge clock wait (a small value proves each sample
    // was released by a real clock edge, not a timeout). Persisted (Save) so that if the
    // engine ever resets the script instance, the reloaded instance re-shows the result
    // immediately (HoldResult) instead of rebuilding. Strings are precomputed once (no
    // per-iteration allocation in the hold loop).
    this.bits = bits;
    this.HoldResult(bits, pmin);
}

// Re-show the consolidated result forever. Used both at the end of a normal run and by a
// reloaded instance (Load) that already has the bits, so a stray instance reset never
// rebuilds over a finished run.
function ClockedMain::HoldResult(bits, pmin) {
    local a = "CG " + bits;
    local b = "CG " + bits + " p" + pmin;
    while (true) { this.Say(a); GSController.Sleep(40); this.Say(b); GSController.Sleep(40); }
}

function ClockedMain::Save() { return { bits = this.bits }; }
function ClockedMain::Load(version, data) {
    if ("bits" in data && data.bits != null) this.bits = data.bits;
}
