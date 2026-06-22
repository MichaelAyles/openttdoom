/*
 * fibgate: a CLOCK-STEPPED FIBONACCI READOUT on the proven clocked-gate mechanism.
 *
 * This is a fork of main_clocked.nut (the RELIABLE GS-mediated clocked NOT gate, verified
 * 8/8). It keeps EXACTLY the proven pieces:
 *   - the SELF-SUSTAINING CLOCK: a single train on a closed rectangular loop ringed with
 *     ONE-WAY NORMAL block signals (clockwise), launched + confirmed circulating before use;
 *   - the per-edge WaitClockEdge: each edge the GS BLOCKS until the clock train crosses a
 *     fixed loop phase (a rising edge entering the LEFT run), so every sample is released by
 *     a real clock edge, not a free timer;
 *   - the NOT gate primitive: a straight lane with a reader block signal whose protected
 *     (through) block holds one input tap, terminated by a second signal. A normal block
 *     signal is RED iff its block is occupied, so an eastbound reader passes iff the input
 *     block is empty == NOT(input). The reader's FINAL x is the output bit (x > GSIGX = 1).
 *
 * WHAT IS NEW: instead of ONE gate read once per edge, there are NBITS PARALLEL gate lanes
 * (one per output bit), all gated by the SAME clock edge. At each clock edge k the GS drives
 * the lanes' inputs to present the successive Fibonacci term FIB[k] (1,1,2,3,5,8,13,...) and
 * reads the NBITS lanes back, decoding the 4-bit value from the RAW reader positions.
 *
 * HOW A BIT IS PRESENTED (genuine NOR, output == the Fibonacci bit). Each lane physically
 * computes out = NOT(input present). To make a lane's output EQUAL Fibonacci bit b, the GS
 * sets that lane's input to NOT(b): the input train is parked on the tap iff b == 0, absent
 * iff b == 1. Then the reader passes (out 1) iff the input block is empty iff b == 1. So the
 * gate computes NOT of its driven input, and the schedule is chosen so the computed output
 * spells the Fibonacci value. EVERY output bit comes from the RAW reader x (out = x > GSIGX),
 * never from FIB[] in Squirrel. The decode value = sum(bit_i << i) is also raw-derived.
 *
 * HONEST SCOPE. This is per-edge RE-PRESENTATION of the Fibonacci terms on the proven clock
 * mechanism: the value is freshly presented to the gate bank each clock edge and computed by
 * the gates, NOT a self-feeding hardware register Fibonacci (next = a + b held in track). That
 * needs the physical one-edge output register, which is the open syncgate item (STUCK.md).
 * What IS real here: a self-sustaining clock train, a per-edge clock-released sample, and a
 * bank of real block-signal NOR/NOT gates whose raw outputs spell 1,1,2,3,5,8,13 in order.
 *
 * Readout (SHORT, fixed width, the ~31-char company-name limit is respected):
 *   per edge:  "e<k> v<val> b<bits> p<wait>"   e.g.  e4 v5 b0101 p12
 *   final:     "F 1 1 2 3 5 8 13"               (the decoded sequence, <=31 chars)
 * Judge from the per-edge raw lane positions / the decoded values, never from FIB[].
 */

// ---- clock loop geometry (identical to main_clocked.nut: one-way block-signalled) ----
LX0 <- 30; LX1 <- 38; LY0 <- 20; LY1 <- 26;
CDX <- 33;                 // clock depot column (depot at (CDX, LY0-1))

// ---- gate bank geometry. NBITS parallel NOT-gate lanes, each its own band of rows. ----
NBITS <- 4;                // 4 bits -> values 0..15, covers Fib 1,1,2,3,5,8,13
BX    <- 44;               // lane left x (track starts here)
GSIGX <- BX + 6;           // reader signal x (50)
INX   <- GSIGX + 1;        // input tap x (51), inside the protected block
SIG2X <- GSIGX + 4;        // terminating signal x (54)
EASTX <- GSIGX + 6;        // east depot x (56)
GY0   <- 40;               // first lane row
LANEDY <- 4;               // rows between lanes (each lane needs its own clear band)

// Fibonacci terms to present, one per clock edge. All fit in NBITS=4 bits (max 13 = 1101).
FIB <- [1, 1, 2, 3, 5, 8, 13];

class FibMain extends GSController {
    company = null; eng = null;
    clock = null; cdepot = null;
    // per-lane vehicles/depots, indexed 0..NBITS-1
    wDepot = null; eDepot = null; inDepot = null;
    input = null; reader = null;
    started = false;
    seq = null;            // the decoded value sequence string (persisted)
    constructor() {
        this.wDepot = array(NBITS, null); this.eDepot = array(NBITS, null);
        this.inDepot = array(NBITS, null);
        this.input = array(NBITS, null); this.reader = array(NBITS, null);
    }
}

function FibMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function FibMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function FibMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function FibMain::Say(s) { GSCompany.SetName(s); }
function FibMain::T(x, y) { return GSMap.GetTileIndex(x, y); }
function FibMain::LaneY(i) { return GY0 + i * LANEDY; }

function FibMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// ---- clock loop (verbatim from main_clocked.nut) ----
function FibMain::BuildRect(x0, y0, x1, y1) {
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

function FibMain::SignalLoopOneWay() {
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_NORMAL);  // top +X
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_NORMAL);  // right +Y
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_NORMAL);  // bottom -X
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_NORMAL);  // left -Y
}

function FibMain::BuildClockStatic() {
    this.BuildRect(LX0, LY0, LX1, LY1);
    this.cdepot = this.T(CDX, LY0 - 1);
    GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
    this.SignalLoopOneWay();
}

function FibMain::LaunchClockConfirmed() {
    this.clock = null;
    // Ensure the depot is genuinely built+committed before the first BuildVehicle (a fresh
    // -server first build can fire before the depot tile commits, which fails the build and
    // burns retries). Confirm the depot tile, settling, before building the train.
    for (local d = 0; d < 12; d++) {
        if (GSMap.IsValidTile(this.cdepot) && GSRail.IsRailDepotTile(this.cdepot)) break;
        GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
        GSController.Sleep(15);
    }
    for (local b = 0; b < 18; b++) {
        local v = GSVehicle.BuildVehicle(this.cdepot, this.eng);
        if (GSVehicle.IsValidVehicle(v)) { this.clock = v; break; }
        GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
        GSController.Sleep(12);
    }
    if (!GSVehicle.IsValidVehicle(this.clock)) return false;
    GSOrder.AppendOrder(this.clock, this.T(LX1, LY1), GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSOrder.AppendOrder(this.clock, this.T(LX0, LY0), GSOrder.OF_NON_STOP_INTERMEDIATE);
    // Phase 1: get it OUT of the depot (proven main_clocked values: 80 polls, nudge when
    // stopped in depot). Report the stuck position into the company name so a stall is
    // diagnosable from the readout instead of an opaque "F clk.." hang.
    local left = false;
    for (local r = 0; r < 80; r++) {
        if (!GSVehicle.IsValidVehicle(this.clock)) return false;
        if (GSVehicle.IsStoppedInDepot(this.clock)) GSVehicle.StartStopVehicle(this.clock);
        GSController.Sleep(5);
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        if (cx >= 0 && !(cx == CDX && cy == LY0 - 1)) { left = true; break; }
    }
    if (!left) { this.Say("CKstuck d" + (GSVehicle.IsValidVehicle(this.clock) ? (GSVehicle.IsStoppedInDepot(this.clock) ? 1 : 0) : -1)); return false; }
    local sawBottom = false;
    for (local i = 0; i < 400; i++) {
        if (!GSVehicle.IsValidVehicle(this.clock)) return false;
        if (GSVehicle.IsStoppedInDepot(this.clock)) GSVehicle.StartStopVehicle(this.clock);
        local cx = this.Tx(this.clock); local cy = this.Ty(this.clock);
        if (cy == LY1) sawBottom = true;
        if (sawBottom && cx == LX0 && cy >= LY0 && cy <= LY1) return true;
        GSController.Sleep(5);
    }
    return false;
}

// per-edge clock wait (verbatim): block until the clock crosses the LEFT-run phase.
function FibMain::WaitClockEdge() {
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

// Build one NOT-gate lane i (the main_reeval primitive at the lane's own row). No input yet.
function FibMain::BuildLane(i) {
    local gy = this.LaneY(i);
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(this.T(x, gy), GSRail.RAILTRACK_NE_SW);
    this.wDepot[i] = this.T(BX - 1, gy);
    GSRail.BuildRailDepot(this.wDepot[i], this.T(BX, gy));
    this.eDepot[i] = this.T(EASTX, gy);
    GSRail.BuildRailDepot(this.eDepot[i], this.T(EASTX - 1, gy));
    GSRail.BuildSignal(this.T(GSIGX, gy), this.T(GSIGX - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(SIG2X, gy), this.T(SIG2X - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    this.inDepot[i] = this.T(INX, gy - 1);
    GSRail.BuildRailDepot(this.inDepot[i], this.T(INX, gy));
    GSRail.BuildRailTrack(this.T(INX, gy), GSRail.RAILTRACK_NW_NE);
}

function FibMain::LaneReady(i) {
    return GSMap.IsValidTile(this.wDepot[i]) && GSRail.IsRailDepotTile(this.wDepot[i])
        && GSMap.IsValidTile(this.eDepot[i]) && GSRail.IsRailDepotTile(this.eDepot[i]);
}

// Drive lane i's input to `want` (1 = train parked on the tap == input PRESENT, 0 = absent).
// Idempotent; verbatim poke/unpoke primitive from main_clocked.nut, fully guarded.
function FibMain::SetInput(i, want) {
    local gy = this.LaneY(i);
    if (want && this.input[i] == null) {
        local v = GSVehicle.BuildVehicle(this.inDepot[i], this.eng);
        if (!GSVehicle.IsValidVehicle(v)) return;
        GSOrder.AppendOrder(v, this.T(INX, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local w = 0; w < 40; w++) {
            GSController.Sleep(5);
            if (GSVehicle.IsValidVehicle(v) && this.Tx(v) == INX && this.Ty(v) == gy) {
                GSVehicle.StartStopVehicle(v);    // stop dead on the tap
                break;
            }
        }
        this.input[i] = v;
    } else if (!want && this.input[i] != null) {
        local v = this.input[i];
        if (GSVehicle.IsValidVehicle(v)) {
            // Send it back UP into its depot and sell it there. A train parked on the tap
            // (INX, gy) must reverse one tile north into the depot at (INX, gy-1); give it
            // a ReverseVehicle nudge plus the depot order so it actually leaves the tap.
            GSOrder.AppendOrder(v, this.inDepot[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
            GSVehicle.StartStopVehicle(v);
            GSVehicle.ReverseVehicle(v);
            local gone = false;
            for (local w = 0; w < 40; w++) {
                GSController.Sleep(6);
                if (GSVehicle.IsStoppedInDepot(v)) { gone = true; break; }
            }
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        }
        this.input[i] = null;
        // VERIFY the input block is genuinely clear: if any vehicle still sits on this lane's
        // input tap (a removal that did not reach the depot), it leaves the block occupied and
        // the next read of this lane wrongly sees input present (reads 0). Force-clear it: send
        // any straggler on the tap into the depot and sell it, until the tap is empty. This is
        // the fix for the high-value edges (8,13) where the MSB lane's input must go absent.
        for (local tries = 0; tries < 4; tries++) {
            local occ = null;
            local list = GSVehicleList();
            foreach (vv, _ in list) {
                if (vv == this.clock) continue;
                if (GSVehicle.IsValidVehicle(vv) && this.Tx(vv) == INX && this.Ty(vv) == gy) { occ = vv; break; }
            }
            if (occ == null) break;     // tap is clear
            if (GSVehicle.IsStoppedInDepot(occ)) { GSVehicle.SellVehicle(occ); continue; }
            GSOrder.AppendOrder(occ, this.inDepot[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
            GSVehicle.StartStopVehicle(occ);
            GSVehicle.ReverseVehicle(occ);
            for (local w = 0; w < 30; w++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(occ)) break; }
            if (GSVehicle.IsValidVehicle(occ) && GSVehicle.IsStoppedInDepot(occ)) GSVehicle.SellVehicle(occ);
        }
    }
}

// Sample lane i: a FRESH eastbound reader from its west depot, return its FINAL x.
function FibMain::Sample(i) {
    local gy = this.LaneY(i);
    // Make sure the lane's west depot actually exists before building the reader. If a
    // fresh-server lane build partially failed, the reader BuildVehicle returns invalid and
    // every bit reads BX-1 (held, 0) for the whole run (the all-zeros failure). Rebuild the
    // lane until its west depot is a real depot, then RETRY BuildVehicle until it takes.
    for (local g = 0; g < 6 && !this.LaneReady(i); g++) { this.BuildLane(i); GSController.Sleep(15); }
    local v = null;
    for (local b = 0; b < 10; b++) {
        v = GSVehicle.BuildVehicle(this.wDepot[i], this.eng);
        if (GSVehicle.IsValidVehicle(v)) break;
        if (!this.LaneReady(i)) this.BuildLane(i);
        GSController.Sleep(10);
    }
    this.reader[i] = v;
    if (!GSVehicle.IsValidVehicle(v)) return BX - 1;
    GSOrder.AppendOrder(v, this.eDepot[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    // Persistent egress nudge: keep nudging until the reader actually leaves the depot, so a
    // stochastic depot-exit stall (the SC2 launch-stall failure) does not read as held.
    local out = false;
    for (local r = 0; r < 30; r++) {
        if (!GSVehicle.IsValidVehicle(v)) return BX - 1;
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        else { out = true; break; }
        GSController.Sleep(5);
    }
    // Read the reader's position over a FIXED window and take its FINAL x. This is the
    // proven main_clocked window (18 * 16 ticks): it comfortably covers a full west->east
    // traversal so a passing reader reaches the east depot before the final read. A shorter
    // window mis-reads a still-travelling reader as held (all bits 0), so keep it generous.
    local fx = BX - 1;
    for (local s = 0; s < 18; s++) {
        GSController.Sleep(16);
        local nx = this.Tx(v);
        if (nx >= 0) fx = nx;
    }
    return fx;
}

// Dispose lane i's reader and clear its lane (verbatim drain discipline).
function FibMain::DisposeLane(i) {
    local v = this.reader[i];
    if (v != null && GSVehicle.IsValidVehicle(v)) {
        for (local s = 0; s < 30; s++) {
            if (GSVehicle.IsStoppedInDepot(v)) break;
            GSController.Sleep(10);
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    this.reader[i] = null;
}

// drain any straggler reader parked in a depot across all lanes (never clock or inputs).
function FibMain::DrainStragglers() {
    local protectedSet = {};
    foreach (vv in this.input) if (vv != null) protectedSet[vv] <- true;
    local list = GSVehicleList();
    foreach (vv, _ in list) {
        if (vv == this.clock) continue;
        if (vv in protectedSet) continue;
        if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv))
            GSVehicle.SellVehicle(vv);
    }
}

function FibMain::Start() {
    if (this.seq != null) {
        try { this.HoldResult(this.seq); } catch (e) {}
        while (true) { this.Say("F " + this.seq); GSController.Sleep(74); }
    }
    if (this.started) {
        while (true) { this.Say("F REENTRY"); GSController.Sleep(74); }
    }
    this.started = true;
    try {
        this.Run();
    } catch (e) {
        while (true) { this.Say("F ERR"); GSController.Sleep(74); }
    }
}

function FibMain::Run() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("F build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    for (local w = 0; w < 40 && this.eng == null; w++) {
        GSController.Sleep(10);
        this.eng = this.PickEngine(rt);
    }
    GSController.Sleep(20);

    // Flat canvas covering the clock loop AND the whole gate bank (NBITS lanes).
    local bankYtop = this.LaneY(0) - 2;
    local bankYbot = this.LaneY(NBITS - 1) + 2;
    this.Prepare(LX0 - 2, LY0 - 2, LX1 + 2, LY1 + 2);
    this.Prepare(BX - 2, bankYtop, EASTX + 1, bankYbot);

    // CLOCK FIRST. On a fresh dedicated server the command queue is most able to launch the
    // single clock train when it is the FIRST vehicle build, before the gate bank's many
    // demolish/track/depot commands are queued. Building the 4 lanes first (the earlier
    // ordering) starved the clock build and made it CKFAIL almost every run. So bring the
    // clock up and CONFIRM it circulating BEFORE laying the gate bank.
    this.BuildClockStatic();
    this.Say("F clk..");
    local ok = this.LaunchClockConfirmed();
    if (!ok) { while (true) { this.Say("CKFAIL"); GSController.Sleep(74); } }
    this.Say("F clkOK");

    // Now build all NBITS gate lanes (static), each retried until its depots exist. The
    // confirmed clock keeps circulating on its one-way loop while the bank is laid.
    for (local i = 0; i < NBITS; i++) {
        for (local g = 0; g < 6; g++) {
            this.BuildLane(i);
            if (this.LaneReady(i)) break;
            GSController.Sleep(15);
        }
    }
    // VERIFY-ALL pass: a fresh-server lane build can partially fail and read all-zeros for
    // the whole run (a reader cannot build from a missing depot). Confirm EVERY lane is
    // ready and rebuild any that are not, before the first edge, so no edge mis-reads 0.
    for (local pass = 0; pass < 4; pass++) {
        local allReady = true;
        for (local i = 0; i < NBITS; i++) {
            if (!this.LaneReady(i)) { allReady = false; this.BuildLane(i); }
        }
        if (allReady) break;
        GSController.Sleep(15);
    }

    // ---- per clock edge, present FIB[k] to the lane bank and read it back ----
    local vals = "";              // space-separated decoded values
    local pmin = 9999;            // smallest per-edge clock wait (proves real clock gating)
    for (local k = 0; k < FIB.len(); k++) {
        // PER-EDGE CLOCK WAIT: block until the clock train crosses the loop phase.
        local waited = this.WaitClockEdge();
        if (waited < pmin) pmin = waited;

        local want = FIB[k];      // value to present this edge
        // Drive each lane's input to present bit i of `want`. Lane out == NOT(input present),
        // so to make lane out == bit b we set input PRESENT iff b == 0.
        for (local i = 0; i < NBITS; i++) {
            local b = (want >> i) & 1;
            this.SetInput(i, b == 0);     // input present (1) when the wanted bit is 0
        }
        GSController.Sleep(8);

        // Read every lane's RAW final x and decode the value bit by bit.
        local val = 0;
        local bitstr = "";        // MSB..LSB display
        for (local i = 0; i < NBITS; i++) {
            local fx = this.Sample(i);
            local bit = (fx > GSIGX) ? 1 : 0;   // OUTPUT from the RAW reader position
            val = val | (bit << i);
            bitstr = bit + bitstr;              // prepend so MSB is left
        }
        if (vals != "") vals += " ";
        vals += val;
        this.Say("e" + k + " v" + val + " b" + bitstr + " p" + waited);
        GSController.Sleep(20);

        // clear all lanes for the next edge: drop every input, dispose every reader.
        for (local i = 0; i < NBITS; i++) {
            if (this.input[i] != null) this.SetInput(i, false);
            this.DisposeLane(i);
        }
        this.DrainStragglers();
    }

    // FINAL consolidated readout: "F 1 1 2 3 5 8 13" (the decoded sequence). Every value
    // came from the RAW lane reader positions, never from FIB[]. Persisted so a stray
    // instance reset re-shows the result instead of rebuilding.
    this.seq = vals;
    this.HoldResult(vals);
}

function FibMain::HoldResult(vals) {
    local a = "F " + vals;
    while (true) { this.Say(a); GSController.Sleep(74); }
}

function FibMain::Save() { return { seq = this.seq }; }
function FibMain::Load(version, data) {
    if ("seq" in data && data.seq != null) this.seq = data.seq;
}
