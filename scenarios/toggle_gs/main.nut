/*
 * toggle: a SELF-FEEDING 1-BIT TOGGLE (T flip-flop / divide-by-2) on OpenTTD trains.
 *
 * THE HEADLINE. This is the clocked 1-bit register (scenarios/register_gs/main.nut) with the
 * external write SCHEDULE removed and replaced by genuine self-feeding: at each clock edge the
 * next stored bit is NOT(held Q), and NOT(held Q) is produced by a REAL block-signal gate that
 * reads the machine's OWN held state from a RAW reader position. There is NO toggle/Fibonacci
 * array driving the writes. The register's value steps 0,1,0,1,... purely because each next
 * value is NOT of the bit the machine is currently holding, read off hardware.
 *
 * THE PHYSICAL CELL (the held bit Q and its NOT in ONE block signal). Q is the PRESENCE of a
 * parked train on a single HOLD tile (HX) inside a protected block. A parked train persists on
 * its tile indefinitely with no further action, and THAT is the memory: Q=1 == a train sits on
 * HOLD, Q=0 == HOLD empty. HOLD is the protected (through) block of a reader signal at RSIGX,
 * terminated by a second signal at TSIGX. A normal block signal is RED iff its block is
 * occupied. An eastbound reader launched from the west depot therefore resolves to a RAW final
 * position that reads BOTH the held bit and its complement at once:
 *     HOLD occupied (Q=1)  -> reader HELD at RSIGX (x <= RSIGX)   -> read Q=1, and reader did NOT pass
 *     HOLD empty    (Q=0)  -> reader PASSES east   (x >  RSIGX)   -> read Q=0, and reader DID  pass
 * So from the single raw reader position x:
 *     Q    = (x <= RSIGX)      (the block signal is RED == the bit is present)
 *     NEXT = NOT(Q) = (x > RSIGX)   == "the reader passed the signal"
 * The reader PASSING the block signal IS the physical NOT of the held bit: the same block
 * signal that is red-iff-occupied (giving Q) lets the reader through iff NOT occupied (giving
 * NOT Q). NEXT is the reader's raw pass/hold outcome, never 1-q computed in Squirrel. This is
 * exactly the proven block-signal NOT (norgate_gs NOT, clockgate main_clocked) applied to the
 * register's own held bit, so the toggle needs only ONE lane and ONE reader per edge.
 *
 * THE SELF-FEEDING EDGE (the load-bearing honesty). Each clock edge k, after WaitClockEdge:
 *   1. LAUNCH a fresh reader from the west depot and let it resolve against the HELD HOLD train.
 *   2. From its RAW final x:  q = (x <= RSIGX),  next = (x > RSIGX) = NOT(q). Both come from the
 *      one physical block-signal read of the held bit; next is the reader's pass/hold outcome.
 *   3. WRITE BACK next into the register: Write1() iff next==1 (build+park a HOLD train),
 *      Write0() iff next==0 (remove it). The write-back is GS-mediated (pure track feedback hits
 *      the reservation-coupling blocker, syncgate); this is the honest boundary, same as
 *      register_gs. The VALUE written is the hardware read of the held state, not a schedule.
 * So Q[k+1] = next = NOT(Q[k]) from a real block-signal read of the held bit. Across edges Q
 * toggles 0,1,0,1,... with nothing reading a stored next-state sequence.
 *
 * INITIALISATION. Q starts at 0 (HOLD empty: no train built). The held bit sampled at the START
 * of each edge (before that edge's write) is then  Q : 0 1 0 1 0 1  (readout "TG 010101",
 * MSB = the value held entering edge 0). pmin (smallest per-edge clock wait) proves real clock
 * gating.
 *
 * RELIABILITY DISCIPLINE (inherited from register_gs / clockgate main_clocked, hard-won):
 *  - clock launch is flaky -> RETRY BuildVehicle + StartStop, CONFIRM a full lap before any
 *    sampling; on failure set "CKFAIL" and stop cleanly. (A CKFAIL run is discarded; the
 *    back-to-back run script just relaunches.)
 *  - START THE IDLE AI, never a bare random AI: a random AI (e.g. LoopBench) floods the company
 *    with its own trains, which GSVehicleList then counts. (The run script uses start_ai Idle.)
 *  - the company name has a ~31-char limit; SetName silently no-ops past it. EVERY readout is
 *    SHORT and fixed-width.
 *  - the HOLD train (the stored bit) is never confused with a reader: readers run the lane and
 *    are disposed each edge by the proven register_gs path (lift HOLD to free a held reader, let
 *    it roll east, sell it, restore HOLD); the HOLD train is a manually-stopped vehicle the
 *    final drain explicitly skips.
 *  - ALL vehicle ops guarded; Run() wrapped in try/catch + a re-entry guard so a stray reset
 *    never rebuilds over a finished run (which would grow the train count).
 */

// ---- clock loop geometry (register_gs / clockgate main_clocked: one-way block-signalled) ----
LX0 <- 30; LX1 <- 37; LY0 <- 20; LY1 <- 25;
CDX <- 33;                 // clock depot column (depot at (CDX, LY0-1))

// ---- register lane geometry (the held bit Q lives here; its reader also computes NOT Q) ----
BX     <- 40;              // lane west end
RSIGX  <- BX + 6;          // reader block signal x (46): reader passes iff HOLD empty == NOT(Q)
HX     <- RSIGX + 1;       // HOLD tile x (47): the stored bit lives here, inside the block
TSIGX  <- RSIGX + 4;       // terminating signal x (50): makes HOLD a through block
EASTX  <- RSIGX + 6;       // reader east depot x (52)
GY     <- 40;              // lane row

class ToggleMain extends GSController {
    company = null; eng = null;
    clock = null; cdepot = null;
    wDepot = null; eDepot = null; holdDepot = null;
    hold = null;             // the persistent HOLD train (the stored bit Q), or null
    reader = null;
    started = false;
    bits = null;
    built = 0;               // global vehicle-build counter (runaway safety cap)
    lastx = -1;              // last reader final x (the raw source of both Q and NOT Q)
    constructor() {}
}

function ToggleMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function ToggleMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function ToggleMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function ToggleMain::Say(s) { GSCompany.SetName(s); }
function ToggleMain::T(x, y) { return GSMap.GetTileIndex(x, y); }

// Remove ALL orders from a vehicle so a fresh single order does not oscillate against leftover
// orders. The HOLD token is REUSED across lift/restore cycles, so clear it before each move.
function ToggleMain::ClearOrders(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    while (GSOrder.GetOrderCount(v) > 0) {
        if (!GSOrder.RemoveOrder(v, 0)) break;
    }
}

function ToggleMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// ---- clock loop (verbatim mechanism from register_gs / clockgate main_clocked) ----
function ToggleMain::BuildRect(x0, y0, x1, y1) {
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
function ToggleMain::SignalLoopOneWay() {
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_NORMAL);
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_NORMAL);
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_NORMAL);
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_NORMAL);
}
function ToggleMain::BuildClockStatic() {
    this.BuildRect(LX0, LY0, LX1, LY1);
    this.cdepot = this.T(CDX, LY0 - 1);
    GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
    this.SignalLoopOneWay();
}
function ToggleMain::LaunchClockConfirmed() {
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
    local left = false;
    for (local r = 0; r < 80; r++) {
        if (!GSVehicle.IsValidVehicle(this.clock)) return false;
        if (GSVehicle.IsStoppedInDepot(this.clock)) GSVehicle.StartStopVehicle(this.clock);
        GSController.Sleep(5);
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        if (cx >= 0 && !(cx == CDX && cy == LY0 - 1)) { left = true; break; }
    }
    if (!left) return false;
    local sawBottom = false;
    for (local i = 0; i < 400; i++) {
        if (!GSVehicle.IsValidVehicle(this.clock)) return false;
        if (GSVehicle.IsStoppedInDepot(this.clock)) GSVehicle.StartStopVehicle(this.clock);
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        if (cy == LY1) sawBottom = true;
        if (sawBottom && cx == LX0 && cy >= LY0 && cy <= LY1)
            return true;
        GSController.Sleep(5);
    }
    return false;
}
// Per-edge clock synchronisation: block until the clock crosses a fixed loop phase (rising edge
// entering the left run). Small return == real edge released it, 300 == a stalled clock.
function ToggleMain::WaitClockEdge() {
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

// ---- register lane (the held bit Q): verbatim from register_gs ----
function ToggleMain::BuildLane() {
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(this.T(x, GY), GSRail.RAILTRACK_NE_SW);
    this.wDepot = this.T(BX - 1, GY);
    GSRail.BuildRailDepot(this.wDepot, this.T(BX, GY));
    this.eDepot = this.T(EASTX, GY);
    GSRail.BuildRailDepot(this.eDepot, this.T(EASTX - 1, GY));
    GSRail.BuildSignal(this.T(RSIGX, GY), this.T(RSIGX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(TSIGX, GY), this.T(TSIGX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    this.holdDepot = this.T(HX, GY - 1);
    GSRail.BuildRailDepot(this.holdDepot, this.T(HX, GY));
    GSRail.BuildRailTrack(this.T(HX, GY), GSRail.RAILTRACK_NW_NE);
}
function ToggleMain::LaneReady() {
    return GSMap.IsValidTile(this.wDepot) && GSRail.IsRailDepotTile(this.wDepot)
        && GSRail.IsRailDepotTile(this.eDepot);
}

// CLOCK-GATED WRITE 1: ensure a train is parked on HOLD (idempotent). The parked train IS Q=1.
function ToggleMain::Write1() {
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

// CLOCK-GATED WRITE 0: remove the parked HOLD train (idempotent). HOLD empty == Q=0.
function ToggleMain::Write0() {
    if (this.hold == null) return;
    local v = this.hold;
    if (GSVehicle.IsValidVehicle(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.holdDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSVehicle.ReverseVehicle(v);
        for (local w = 0; w < 40; w++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.hold = null;
}

// Lift the HOLD train OFF its tile into its feeder depot (the block clears), preserving the HOLD
// vehicle handle. Used only to free a reader HELD at the red signal by HOLD's presence (a Q=1
// read). The bit VALUE is restored immediately after by RestoreHold.
function ToggleMain::LiftHold() {
    local v = this.hold;
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.holdDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    GSVehicle.ReverseVehicle(v);
    for (local s = 0; s < 30; s++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
}

// Re-park the HOLD train back ON its tile (re-establish Q=1 to the SAME value). Only the physical
// token is cycled; the bit's logical value is unchanged. Sells + rebuilds a fresh HOLD token if
// the reused one does not land back on HX.
function ToggleMain::RestoreHold() {
    local v = this.hold;
    if (v != null && GSVehicle.IsValidVehicle(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.T(HX, GY), GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local w = 0; w < 40; w++) {
            GSController.Sleep(5);
            if (this.Tx(v) == HX && this.Ty(v) == GY) { GSVehicle.StartStopVehicle(v); return; }
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.hold = null;
    this.Write1();
}

// READ the held bit and FULLY DISPOSE the reader in one call (verbatim from register_gs, the
// proven leak-free single-lane path). Builds EXACTLY ONE reader from the west depot, runs it
// east, classifies its RAW final x, disposes it, and returns the raw final x in this.lastx plus
// the classification:
//   reader PASSED  (x > RSIGX)        -> HOLD empty    -> return 0  (reader sold at east depot)
//   reader HELD    (BX <= x <= RSIGX) -> HOLD occupied -> return 1  (lift HOLD, reader rolls east,
//                                                                    sold; HOLD restored)
//   reader STUCK   (x < BX)           -> invalid read  -> return -1 (reader sold from depot)
// The caller derives BOTH q and next from the returned classification / this.lastx:
//   q    = (returned == 1)           the held bit (block signal RED == occupied)
//   next = NOT(q) = (this.lastx > RSIGX)   the reader's raw PASS outcome == physical NOT of Q.
function ToggleMain::ReadAndDispose() {
    if (this.built >= 60) return -1;          // hard safety cap; never run the build away
    local v = GSVehicle.BuildVehicle(this.wDepot, this.eng);
    this.built++;
    this.reader = v;
    if (!GSVehicle.IsValidVehicle(v)) return -1;
    GSOrder.AppendOrder(v, this.eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    for (local r = 0; r < 20; r++) {
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(5);
        if (this.Tx(v) >= BX) break;
    }
    local fx = BX - 1;
    local stable = 0; local lastx = -999;
    for (local s = 0; s < 18; s++) {
        GSController.Sleep(9);
        local nx = this.Tx(v);
        if (nx >= 0) fx = nx;
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v) && fx > RSIGX) break;
        if (fx >= BX && fx <= RSIGX) {
            if (fx == lastx) { stable++; if (stable >= 3) break; }
            else stable = 0;
        } else stable = 0;
        lastx = fx;
    }
    local q;
    if (fx > RSIGX) q = 0;
    else if (fx >= BX) q = 1;
    else q = -1;
    if (q == 1) {
        this.LiftHold();
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local s = 0; s < 24; s++) {
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) break;
            GSController.Sleep(8);
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        this.RestoreHold();
    } else {
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

function ToggleMain::Start() {
    if (this.bits != null) {
        try { this.HoldResult(this.bits, 0); } catch (e) {}
        while (true) { this.Say("TG " + this.bits); GSController.Sleep(74); }
    }
    if (this.started) {
        while (true) { this.Say("TG REENTRY"); GSController.Sleep(74); }
    }
    this.started = true;
    try {
        this.Run();
    } catch (e) {
        while (true) { this.Say("TG ERR"); GSController.Sleep(74); }
    }
}

function ToggleMain::Run() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("TG build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    for (local w = 0; w < 40 && this.eng == null; w++) {
        GSController.Sleep(10);
        this.eng = this.PickEngine(rt);
    }
    GSController.Sleep(20);

    // flat canvas: lane row (GY=40) and clock loop rows (20..25) are disjoint.
    this.Prepare(LX0 - 2, LY0 - 2, LX1 + 2, LY1 + 2);
    this.Prepare(BX - 2, GY - 2, EASTX + 1, GY + 2);

    // CLOCK FIRST (fresh-server command queue most reliably launches the single clock train when
    // it is the first vehicle build, before the lane demolish/track/depot commands).
    this.BuildClockStatic();
    this.Say("TG clk..");
    local ok = this.LaunchClockConfirmed();
    if (!ok) { while (true) { this.Say("CKFAIL"); GSController.Sleep(74); } }
    this.Say("TG clkOK");

    // build the lane (retry until both depots exist; a half-built lane jams readers).
    for (local g = 0; g < 6; g++) {
        this.BuildLane();
        if (this.LaneReady()) break;
        GSController.Sleep(15);
    }
    for (local pass = 0; pass < 4 && !this.LaneReady(); pass++) { this.BuildLane(); GSController.Sleep(15); }

    // INITIALISE Q = 0 (HOLD empty already: no train built). From here every value is self-fed:
    // next = NOT(held Q) read off the block signal. Write0 confirms the cell is at 0.
    this.Write0();

    // ---- SELF-FEEDING CLOCK EDGES ----
    // Each edge: read the held bit with one fresh reader; q and next BOTH come from that reader's
    // raw final x (q = held, next = passed = NOT q); write next back. NO toggle array; the only
    // thing that sets the write is the block-signal read of the held bit.
    local NEDGES = 6;
    local bits = "";              // the held Q sampled at the START of each edge (MSB = edge 0)
    local pmin = 9999;
    for (local k = 0; k < NEDGES; k++) {
        local waited = this.WaitClockEdge();
        if (waited < pmin) pmin = waited;

        // READ the held bit (and its physical NOT) from one fresh reader's raw final x.
        local q = -1;
        for (local rd = 0; rd < 3 && q < 0; rd++) q = this.ReadAndDispose();
        bits += (q < 0 ? "e" : q.tostring());

        // DERIVE next = NOT(q) from the SAME raw reader position: the reader passed the block
        // signal iff HOLD was empty iff Q==0. next is the reader's raw pass/hold outcome.
        local next = (q < 0) ? -1 : ((this.lastx > RSIGX) ? 1 : 0);

        // WRITE BACK next into the register (clock-gated GS-mediated write of the hardware read).
        if (next == 1) this.Write1();
        else if (next == 0) this.Write0();
        // (next == -1: read failed; leave Q untouched, the readout shows the failure.)

        local nt = GSVehicleList().Count();
        this.Say("e" + k + " Q" + q + " x" + this.lastx + " N" + next + " n" + nt);
        GSController.Sleep(6);
    }

    // FINAL readout "TG 010101" (MSB = the bit held entering edge 0). Every bit is the RAW reader
    // x (held at RSIGX -> 1, passed -> 0). The toggle 0,1,0,1,... is produced because each next
    // value was the reader's raw PASS outcome (the physical NOT of the held bit), with NO toggle
    // array. pmin proves real clock gating.
    this.bits = bits;
    this.HoldResult(bits, pmin);
}

function ToggleMain::HoldResult(bits, pmin) {
    local a = "TG " + bits;
    local b = "TG " + bits + " p" + pmin;
    while (true) { this.Say(a); GSController.Sleep(40); this.Say(b); GSController.Sleep(40); }
}

function ToggleMain::Save() { return { bits = this.bits }; }
function ToggleMain::Load(version, data) {
    if ("bits" in data && data.bits != null) this.bits = data.bits;
}
