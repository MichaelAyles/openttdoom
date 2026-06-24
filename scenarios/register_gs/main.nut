/*
 * register: a CLOCKED 1-BIT REGISTER (memory cell) on OpenTTD trains.
 *
 * THE STORED BIT. Q is the PRESENCE of a parked train on a single HOLD tile that
 * sits inside a protected block. A parked train persists on its tile indefinitely
 * with no further action, and THAT is the memory. Q=1 == a train sits on HOLD,
 * Q=0 == HOLD is empty.
 *
 * READING Q (the proven block-signal read, scenarios/norgate_gs). The HOLD tile is
 * the protected (through) block of a reader signal at RSIGX, terminated by a second
 * signal at TSIGX. A normal block signal is RED iff its block is occupied. An
 * eastbound reader from the west depot therefore:
 *     Q=1 (HOLD occupied)  -> signal RED   -> reader HELD at RSIGX (x <= RSIGX)
 *     Q=0 (HOLD empty)     -> signal GREEN  -> reader PASSES to the east depot (x > RSIGX)
 * So the read-back bit is  Q = (reader_final_x <= RSIGX), i.e. reader-held == Q. This
 * is derived from the RAW reader x, never from any stored Squirrel flag.
 * BuildSignal(tile, front) permits travel FROM front INTO tile, so the eastbound
 * reader needs front = RSIGX-1, and the block must be a through block (the second
 * terminating signal) or a normal signal in front of a dead end stays red.
 *
 * THE CLOCK (proven self-sustaining loop + per-edge wait, clockgate main_clocked,
 * 8/8). A single train circulates a closed rectangular loop ringed with ONE-WAY
 * NORMAL block signals (clockwise). WaitClockEdge() BLOCKS until the clock train
 * crosses a fixed loop phase (entering the left run), so every per-edge action is
 * released by a REAL clock edge, not a free timer.
 *
 * THE CLOCKED WRITE. A write happens ONLY at a clock edge (gated by WaitClockEdge).
 * write-1: build a train from the HOLD feeder depot and park it dead on HOLD.
 * write-0: send the parked HOLD train to a sink depot and sell it. Between edges Q
 * is never touched, so it HOLDS.
 *
 * THE EXPERIMENT (what proves it is a register, not just "park a train once"):
 *   The cell is initialised to Q=1 (one write at edge 0). Then a fixed schedule of
 *   per-edge actions, each released by its own clock edge:
 *       edge: 0      1     2     3       4     5     6
 *       act : W1     -     -     W0      -     -     W1
 *       (W1 = clock-gated write 1, W0 = clock-gated write 0, - = HOLD, no write)
 *   At EVERY edge, AFTER any write, an independent fresh reader samples Q from the
 *   RAW reader x. The expected read-back sequence is:
 *       Q   : 1      1     1     0       0     0     1
 *   Edges 1,2 (no write) must repeat edge-0's value  -> HOLD proven.
 *   Edge 3 writes 0 and edges 4,5 repeat it          -> clocked UPDATE + HOLD proven.
 *   Edge 6 writes 1 again                            -> a second update.
 *   Readout "RG 1110001" (MSB = edge 0). Every bit is reader_x <= RSIGX on the RAW
 *   position. The reader is disposed each edge and rebuilt fresh, so the bit read at
 *   edge k+1 comes ONLY from the persistent HOLD train, not from a leftover reader.
 *
 * RELIABILITY DISCIPLINE (inherited from clockgate main_clocked, all hard-won):
 *  - clock launch is flaky -> RETRY BuildVehicle + StartStop, CONFIRM a full lap
 *    before any sampling; on failure set "CKFAIL" and stop cleanly.
 *  - the company name has a ~31-char limit; SetName silently no-ops past it. EVERY
 *    readout here is SHORT and fixed-width.
 *  - the HOLD train must never be confused with a reader: readers run the lane and
 *    are disposed each edge; the HOLD train is parked off the reader's running line
 *    sense (it sits ON the lane at HX but is a manually-stopped vehicle, and the
 *    drain step explicitly skips it).
 *  - ALL vehicle ops guarded; Run() wrapped in try/catch + a re-entry guard so a
 *    stray reset never rebuilds over a finished run (which would grow the train count).
 */

// ---- clock loop geometry (clockgate main_clocked: one-way block-signalled, single train) ----
// Same proven mechanism; a slightly smaller rectangle so the lap period (the per-edge
// wall-clock cost) is shorter and the whole run finishes inside the budget.
LX0 <- 30; LX1 <- 37; LY0 <- 20; LY1 <- 25;
CDX <- 33;                 // clock depot column (depot at (CDX, LY0-1))

// ---- register lane geometry (its own rows, well clear of the clock loop) ----
BX     <- 40;              // lane west end
RSIGX  <- BX + 6;          // reader block signal x (46): reader passes iff HOLD empty
HX     <- RSIGX + 1;       // HOLD tile x (47): the stored bit lives here, inside the block
TSIGX  <- RSIGX + 4;       // terminating signal x (50): makes HOLD a through block
EASTX  <- RSIGX + 6;       // reader east depot x (52)
GY     <- 40;              // lane row

class RegisterMain extends GSController {
    company = null; eng = null;
    clock = null; cdepot = null;
    wDepot = null; eDepot = null; holdDepot = null;
    hold = null;             // the persistent HOLD train (the stored bit), or null
    reader = null;
    started = false;
    bits = null;
    built = 0;               // global vehicle-build counter (runaway safety cap)
    lastx = -1;              // last reader final x (for the per-edge readout)
    constructor() {}
}

function RegisterMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function RegisterMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function RegisterMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function RegisterMain::Say(s) { GSCompany.SetName(s); }
function RegisterMain::T(x, y) { return GSMap.GetTileIndex(x, y); }

// Remove ALL orders from a vehicle so a fresh single order does not oscillate against
// leftover orders. The HOLD token is REUSED across lift/restore cycles, so its order
// list must be cleared before each new movement or it ping-pongs between stale targets.
function RegisterMain::ClearOrders(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    while (GSOrder.GetOrderCount(v) > 0) {
        if (!GSOrder.RemoveOrder(v, 0)) break;
    }
}

function RegisterMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// ---- clock loop (verbatim mechanism from clockgate main_clocked) ----
function RegisterMain::BuildRect(x0, y0, x1, y1) {
    for (local x = x0 + 1; x < x1; x++) {
        GSRail.BuildRailTrack(this.T(x, y0), GSRail.RAILTRACK_NE_SW);
        GSRail.BuildRailTrack(this.T(x, y1), GSRail.RAILTRACK_NE_SW);
    }
    for (local y = y0 + 1; y < y1; y++) {
        GSRail.BuildRailTrack(this.T(x0, y), GSRail.RAILTRACK_NW_SE);
        GSRail.BuildRailTrack(this.T(x1, y), GSRail.RAILTRACK_NW_SE);
    }
    GSRail.BuildRailTrack(this.T(x0, y0), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(this.T(x1, y0), GSRail.RAILTRACK_NE_SE);
    GSRail.BuildRailTrack(this.T(x1, y1), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(x0, y1), GSRail.RAILTRACK_NW_SW);
}
function RegisterMain::SignalLoopOneWay() {
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_NORMAL);
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_NORMAL);
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_NORMAL);
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_NORMAL);
}
function RegisterMain::BuildClockStatic() {
    this.BuildRect(LX0, LY0, LX1, LY1);
    this.cdepot = this.T(CDX, LY0 - 1);
    GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
    this.SignalLoopOneWay();
}
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

// One-shot, settle-verified depot egress. Fires AT MOST one start toggle per SETTLE so a queued
// toggle is never double-fired (the old bug). True once the clock leaves the depot tile.
function RegisterMain::NudgeEgress(v) {
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

function RegisterMain::LaunchOnce() {
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
        if (cy == LY1) sawBottom = true;
        if (sawBottom && cx == LX0 && cy >= LY0 && cy <= LY1)
            return true;
        GSController.Sleep(5);
    }
    return false;
}

// Sell a stuck/leftover clock train between launch retries (so a failed attempt never leaves a
// train on the loop that would block the next). Returns true only once the loop is CONFIRMED
// clear (parked and sold, or already gone). A moving train is NEVER sold (SellVehicle fails
// mid-track and would leak a second train onto the one-way loop): it is ordered into the depot
// and we wait beyond a full lap; this.clock is kept until the train is actually gone so a retry
// can re-target it. Fully guarded.
function RegisterMain::TeardownClock() {
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

function RegisterMain::LaunchClockConfirmed() {
    for (local t = 0; t < 4; t++) {
        if (this.LaunchOnce()) return true;
        this.Say("RG clkR" + t);
        for (local d = 0; d < 4 && !this.TeardownClock(); d++) GSController.Sleep(20);
        GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
        GSController.Sleep(20);
    }
    return false;
}
// Per-edge clock synchronisation: block until the clock crosses a fixed loop phase
// (rising edge entering the left run). Returns the sleeps waited (small == a real
// edge released it, 300 == a stalled clock).
function RegisterMain::WaitClockEdge() {
    local waited = 0;
    local wasOff = false;
    for (local i = 0; i < 300; i++) {
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        local onLeft = (cx == LX0 && cy >= LY0 && cy <= LY1);
        if (onLeft && wasOff) return waited;
        if (!onLeft && cx >= 0) wasOff = true;
        GSController.Sleep(4);
        waited++;
    }
    return waited;
}

// ---- register lane ----
// Build the lane ONCE: straight track BX..EASTX, west + east depots, reader signal
// at RSIGX and terminating signal at TSIGX (so HOLD at HX is a through block), and a
// HOLD feeder depot just NORTH of HX with a join so a write-1 train can roll onto HX.
function RegisterMain::BuildLane() {
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(this.T(x, GY), GSRail.RAILTRACK_NE_SW);
    this.wDepot = this.T(BX - 1, GY);
    GSRail.BuildRailDepot(this.wDepot, this.T(BX, GY));
    this.eDepot = this.T(EASTX, GY);
    GSRail.BuildRailDepot(this.eDepot, this.T(EASTX - 1, GY));
    GSRail.BuildSignal(this.T(RSIGX, GY), this.T(RSIGX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(TSIGX, GY), this.T(TSIGX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    // HOLD feeder depot north of HX, joined to the lane so a built train rolls onto HX.
    this.holdDepot = this.T(HX, GY - 1);
    GSRail.BuildRailDepot(this.holdDepot, this.T(HX, GY));
    GSRail.BuildRailTrack(this.T(HX, GY), GSRail.RAILTRACK_NW_NE);
}

// CLOCK-GATED WRITE 1: ensure a train is parked on HOLD (idempotent). Build from the
// HOLD feeder depot, send it to HX, stop it dead there. The parked train IS Q=1.
function RegisterMain::Write1() {
    if (this.hold != null && GSVehicle.IsValidVehicle(this.hold)
        && this.Tx(this.hold) == HX && this.Ty(this.hold) == GY) return;  // already held
    local v = GSVehicle.BuildVehicle(this.holdDepot, this.eng);
    this.built++;
    if (!GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.T(HX, GY), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 50; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && this.Tx(v) == HX && this.Ty(v) == GY) {
            GSVehicle.StartStopVehicle(v);   // stop dead on HOLD: the bit is now 1
            break;
        }
    }
    this.hold = v;
}

// CLOCK-GATED WRITE 0: remove the parked HOLD train (idempotent). Send it back to its
// feeder depot and sell it. HOLD empty == Q=0.
function RegisterMain::Write0() {
    if (this.hold == null) return;
    local v = this.hold;
    if (GSVehicle.IsValidVehicle(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.holdDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);  // resume from manual stop
        GSVehicle.ReverseVehicle(v);  // it faces into the lane; reverse to back into its depot
        for (local w = 0; w < 40; w++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.hold = null;
}

// Lift the HOLD train OFF its tile into its feeder depot (the block clears), preserving
// the HOLD vehicle handle. Used only to free a reader HELD at the red signal by HOLD's
// presence (a Q=1 read). The bit VALUE is restored immediately after by RestoreHold.
function RegisterMain::LiftHold() {
    local v = this.hold;
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.holdDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    GSVehicle.ReverseVehicle(v);          // it faces into the lane; reverse to back into its depot
    for (local s = 0; s < 30; s++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
}

// Re-park the HOLD train back ON its tile (re-establish Q=1 to the SAME value). Only the
// physical token is cycled; the bit's logical value is unchanged. Sells + rebuilds a fresh
// HOLD token if the reused one does not land back on HX.
function RegisterMain::RestoreHold() {
    local v = this.hold;
    if (v != null && GSVehicle.IsValidVehicle(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.T(HX, GY), GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local w = 0; w < 40; w++) {
            GSController.Sleep(5);
            if (this.Tx(v) == HX && this.Ty(v) == GY) { GSVehicle.StartStopVehicle(v); return; }
        }
        // did not land on HX: drop it and rebuild fresh.
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.hold = null;
    this.Write1();
}

// READ Q and FULLY DISPOSE the reader in one call (no reader ever survives this function,
// so the lane cannot fill up). Builds EXACTLY ONE reader from the west depot, runs it east,
// classifies the result, disposes it, and returns the bit:
//   reader PASSED  (x > RSIGX)        -> HOLD empty    -> return 0  (reader sold at east depot)
//   reader HELD    (BX <= x <= RSIGX) -> HOLD occupied -> return 1  (lift HOLD, reader rolls
//                                                                    east, sold; HOLD restored)
//   reader STUCK   (x < BX)           -> invalid read  -> return -1 (reader sold from depot)
// A global build counter (this.built) caps total vehicle builds so a stuck state can never
// run away; on the cap it returns -1 and the caller aborts cleanly.
function RegisterMain::ReadAndDispose() {
    if (this.built >= 60) return -1;          // hard safety cap; never run the build away
    local v = GSVehicle.BuildVehicle(this.wDepot, this.eng);
    this.built++;
    this.reader = v;
    if (!GSVehicle.IsValidVehicle(v)) return -1;
    GSOrder.AppendOrder(v, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    // launch out of the depot.
    for (local r = 0; r < 20; r++) {
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(5);
        if (this.Tx(v) >= BX) break;
    }
    // read window: settle to a final x. A PASSING reader (HOLD empty) runs east into the
    // east depot. A HELD reader (HOLD occupied) stops dead just west of RSIGX. We break when
    // the reader is depot-stopped past RSIGX (passed) OR its x has been STABLE in the held
    // band for 3 polls (genuinely stopped at the red signal, not merely mid-transit).
    local fx = BX - 1;
    local stable = 0; local lastx = -999;
    for (local s = 0; s < 18; s++) {
        GSController.Sleep(9);
        local nx = this.Tx(v);
        if (nx >= 0) fx = nx;
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v) && fx > RSIGX) break;  // passed -> east depot
        if (fx >= BX && fx <= RSIGX) {                          // possibly held at the red signal
            if (fx == lastx) { stable++; if (stable >= 3) break; }   // x stopped changing -> settled
            else stable = 0;
        } else stable = 0;
        lastx = fx;
    }
    // classify.
    local q;
    if (fx > RSIGX) q = 0;
    else if (fx >= BX) q = 1;
    else q = -1;
    // DISPOSE this single reader completely (the lane ends empty of readers).
    if (q == 1) {
        // held at RSIGX by HOLD: lift HOLD so the reader rolls east, sell it, restore HOLD.
        this.LiftHold();
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local s = 0; s < 24; s++) {
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) break;
            GSController.Sleep(8);
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        this.RestoreHold();
    } else {
        // passed (q=0) or stuck (q=-1): route it to a depot and sell. If on the lane and not
        // moving (stuck west), order it east; HOLD is empty in these cases so the lane is clear.
        if (GSVehicle.IsValidVehicle(v) && !GSVehicle.IsStoppedInDepot(v)) {
            GSOrder.AppendOrder(v, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
            for (local s = 0; s < 20; s++) {
                if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) break;
                GSController.Sleep(8);
            }
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.reader = null;
    // final safety: sell ANY non-clock, non-HOLD vehicle parked in a depot (catches a dud).
    foreach (vv, _ in GSVehicleList()) {
        if (vv == this.clock || vv == this.hold) continue;
        if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv)) GSVehicle.SellVehicle(vv);
    }
    this.lastx = fx;
    return q;
}

function RegisterMain::Start() {
    if (this.bits != null) {
        try { this.HoldResult(this.bits, 0); } catch (e) {}
        while (true) { this.Say("RG " + this.bits); GSController.Sleep(74); }
    }
    if (this.started) {
        while (true) { this.Say("RG REENTRY"); GSController.Sleep(74); }
    }
    this.started = true;
    try {
        this.Run();
    } catch (e) {
        while (true) { this.Say("RG ERR"); GSController.Sleep(74); }
    }
}

function RegisterMain::Run() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("RG build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    for (local w = 0; w < 40 && this.eng == null; w++) {
        GSController.Sleep(10);
        this.eng = this.PickEngine(rt);
    }
    GSController.Sleep(20);

    // flat canvas: lane rows (around GY=40) and clock loop rows (20..26) are disjoint.
    this.Prepare(BX - 2, GY - 2, EASTX + 1, GY + 2);
    this.Prepare(LX0 - 2, LY0 - 2, LX1 + 2, LY1 + 2);

    // build the lane (retry until both depots exist; a half-built lane jams readers).
    for (local g = 0; g < 6; g++) {
        this.BuildLane();
        if (GSMap.IsValidTile(this.wDepot) && GSRail.IsRailDepotTile(this.wDepot)
            && GSRail.IsRailDepotTile(this.eDepot)) break;
        GSController.Sleep(15);
    }
    this.BuildClockStatic();
    this.Say("RG clk..");
    local ok = this.LaunchClockConfirmed();
    if (!ok) { while (true) { this.Say("CKFAIL"); GSController.Sleep(74); } }
    this.Say("RG clkOK");

    // PER-EDGE ACTION SCHEDULE. 1 = clock-gated write 1, 0 = clock-gated write 0,
    // -1 = HOLD (no write). Expected read-back Q = 1,1,1,0,0.
    //   edge: 0   1   2   3   4
    //   act : W1  -   -   W0  -
    // Edges 1,2 (no write) must repeat edge-0's value -> the bit HOLDS across edges.
    // Edge 3 writes 0 and edge 4 (no write) holds it  -> clocked UPDATE then HOLD.
    // Five edges keeps the whole run inside the wall-clock budget (each edge is gated by a
    // full clock period of the train loop).
    local acts = [1, -1, -1, 0, -1];
    local bits = "";
    local pmin = 9999;
    for (local k = 0; k < acts.len(); k++) {
        // PER-EDGE CLOCK WAIT: the per-edge action and the read are both released by a
        // real clock edge crossing the loop phase.
        local waited = this.WaitClockEdge();
        if (waited < pmin) pmin = waited;
        // perform this edge's clock-gated action (or hold).
        if (acts[k] == 1) this.Write1();
        else if (acts[k] == 0) this.Write0();
        // (acts[k] == -1: HOLD, do nothing; Q must persist on its own.)
        GSController.Sleep(4);
        // READ Q from the persistent HOLD state with ONE fresh reader, fully disposed inside
        // ReadAndDispose (so the lane never fills). If a read comes back INVALID (q=-1, the
        // reader never left the depot), re-read up to a couple times; each read disposes its
        // own reader, so retries do not pile up trains.
        local q = -1;
        for (local rd = 0; rd < 3 && q < 0; rd++) {
            q = this.ReadAndDispose();
        }
        bits += (q < 0 ? "e" : q.tostring());
        local nt = GSVehicleList().Count();
        this.Say("e" + k + " x" + this.lastx + " q" + q + " n" + nt + " b" + this.built);
        GSController.Sleep(6);
    }

    // FINAL readout "RG 11100" (MSB = edge 0). Every bit is from the RAW reader x (held at
    // RSIGX -> 1, passed -> 0); on the -1 (HOLD) edges no write touches HOLD, so a repeat
    // read of the same bit is the bit HOLDING with no input. pmin proves real clock gating.
    this.bits = bits;
    this.HoldResult(bits, pmin);
}

function RegisterMain::HoldResult(bits, pmin) {
    local a = "RG " + bits;
    local b = "RG " + bits + " p" + pmin;
    while (true) { this.Say(a); GSController.Sleep(40); this.Say(b); GSController.Sleep(40); }
}

function RegisterMain::Save() { return { bits = this.bits }; }
function RegisterMain::Load(version, data) {
    if ("bits" in data && data.bits != null) this.bits = data.bits;
}
