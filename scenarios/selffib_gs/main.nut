/*
 * selffib: a SELF-FEEDING FIBONACCI on OpenTTD trains. 1,1,2,3,5,8,13... computed from
 * the machine's OWN held register state, on the hardened clock launch.
 *
 * THE HEADLINE. Two multi-bit registers a and b are HELD in track (each bit = a parked
 * train on a HOLD tile, exactly the register_gs / toggle_gs cell). Each clock edge:
 *   (1) READ a and b out of their held registers via RAW reader positions (the proven
 *       block-signal read: a fresh eastbound reader is HELD iff the HOLD tile is occupied,
 *       judged from the raw final x, never a Squirrel flag);
 *   (2) COMPUTE next = a + b with a REAL block-signal NOR full adder. Each sum bit and each
 *       carry is the raw PASS/HOLD outcome of a block-signal NOR gate, composed in the
 *       NOR-only full-adder form (NOR is universal). NO a+b is computed arithmetically in
 *       Squirrel, and there is NO Fibonacci/sequence array;
 *   (3) SHIFT: write a <- b and b <- next back into the held registers (GS-mediated write,
 *       the honest boundary, same as register_gs / toggle_gs);
 *   (4) READ OUT next.
 * So term[k+1] = (term[k] + term[k-1]) produced by the machine feeding its OWN held state
 * back through real gates. Initialised a=0, b=1, giving 1,1,2,3,5,8,13.
 *
 * THE HELD BIT (register_gs cell, one per register bit). Q is the PRESENCE of a parked train
 * on a HOLD tile inside a protected (through) block. A normal block signal is RED iff its
 * block is occupied, so a fresh eastbound reader from the west depot is HELD (x <= RSIGX) iff
 * the HOLD train is present (bit 1), and PASSES east (x > RSIGX) iff HOLD is empty (bit 0).
 * The read bit is Q = (reader_x <= RSIGX) from the RAW reader x. A parked train persists
 * forever: THAT is the memory.
 *
 * THE NOR FULL ADDER (real gates, every output read at a raw position). The only buildable
 * gate is the block-signal NOR (norgate_gs): a reader passes a signal iff EVERY input tap in
 * the protected block is empty. NOR is universal, so a full adder is built from NOR gates:
 *     n1 = NOR(a, b)
 *     n2 = NOR(a, n1)
 *     n3 = NOR(b, n1)
 *     n4 = NOR(n2, n3)          = a XOR b
 *     n5 = NOR(n4, c)
 *     n6 = NOR(n4, n5)
 *     n7 = NOR(c, n5)
 *     sum  = NOR(n6, n7)        = a XOR b XOR c
 *     cout = NOR(n5, n1)        = majority(a, b, c)
 * Each NOR is one PHYSICAL block-signal read: park the two input bits (re-materialised as
 * trains on the two taps of the gate lane), run a fresh reader, and read its raw pass/hold
 * outcome (x > SIGX => 1). The output of every gate, including sum and cout, is a RAW reader
 * position, exactly as norchain composed gate1's raw output into gate2's input. So sum_i and
 * cout_i are read from raw positions, NOT computed in Squirrel; the only Squirrel role is
 * wiring which raw output feeds which next-gate tap (the netlist), the same role norchain's
 * coupling spur plays in hardware. The carry ripples bit-to-bit as a real read fed forward.
 *
 * THE SELF-FEEDING SHIFT (the load-bearing honesty). After next = a + b is read bit-by-bit
 * off the gates, SHIFT the window: a <- b, b <- next. The writes are GS-mediated (build/park a
 * HOLD train for a 1 bit, remove it for a 0 bit), the same honest boundary as register_gs /
 * toggle_gs. The VALUES written are the hardware reads of the held state, never a stored
 * sequence.
 *
 * RELIABILITY (honest, low-yield BY DESIGN). Reliability compounds: per edge we do NBITS
 * register reads x2 plus NBITS x 9 NOR-gate reads plus the clock wait and the shift writes,
 * each of which is the ~2/3-to-4/5 reliable train-dispatch primitive. So a full 4-bit edge is
 * the product of ~50 fragile reads. The run reports every per-edge readout and exactly how
 * many output terms self-fed before a read failed. An honest partial (e.g. 1,1,2,3 self-fed)
 * with the mechanism pinned is the expected real result. NEDGES, NBITS are small to fit the
 * wall-clock budget.
 *
 * READOUT (SHORT, the ~31-char company-name limit). Per edge: "e<k> a<av> b<bv> s<sum>".
 * Final: "FF <t0> <t1> ..." the output terms (the next read each edge), judged from the raw
 * per-edge reads. A failed read shows "e" in the term list and stops the run there.
 */

// ===================== GEOMETRY =====================
// Clock loop (verbatim from register_gs / toggle_gs / clockgate main_clocked).
LX0 <- 30; LX1 <- 37; LY0 <- 20; LY1 <- 25;
CDX <- 33;

// Register width. a and b are NBITS bits; next = a+b needs NBITS+1 bits. With 2-bit registers
// the window holds 0..3, so the self-fed output is 1,1,2,3 (the honest-partial target: b reaches
// 3, and 2+3=5 would overflow a 2-bit b, which is exactly where a clean machine stops). Each
// edge does ~2 register reads/bit + the per-bit NOR full adder; reliability compounds, so 2 bits
// (fewer gate reads per edge) maximises the chance of reproducing the early terms.
NBITS <- 2;
SBITS <- NBITS + 1;

// Register-bit cell x layout (verbatim register_gs lane), reused per bit on its own row.
BX     <- 40;
RSIGX  <- BX + 6;          // reader signal x (46): reader passes iff this bit's HOLD empty
HX     <- RSIGX + 1;       // HOLD tile x (47): the stored bit lives here
TSIGX  <- RSIGX + 4;       // terminating signal x (50): makes HOLD a through block
EASTX  <- RSIGX + 6;       // reader east depot x (52)

AY0 <- 40;                 // register a rows 40,43,46,49
BY0 <- 56;                 // register b rows 56,59,62,65
RROWSTEP <- 3;

// NOR gate lane (one reusable 2-input NOR per bit position, on its own row). Same primitive as
// norgate_gs main_nor2: reader signal at GSIGX, two input taps, terminating signal, east depot.
GBX    <- 40;              // gate lane west end / west depot at GBX-1
GSIGX  <- GBX + 6;         // gate reader signal x (46): reader passes iff both taps empty (NOR)
GTAP0  <- GSIGX + 1;       // gate input tap 0 (47)
GTAP1  <- GSIGX + 2;       // gate input tap 1 (48)
GTERMX <- GSIGX + 4;       // gate terminating signal x (50)
GEASTX <- GSIGX + 6;       // gate east depot x (52)
GY0    <- 72;              // gate lanes rows 72,75,78,81 (one per bit)

class FibMain extends GSController {
    company = null; eng = null;
    clock = null; cdepot = null;
    started = false;
    terms = null;            // final output-term string (persisted)
    built = 0;               // global vehicle-build counter (runaway safety cap)
    aHold = null; bHold = null;            // held register tokens per bit (or null = 0)
    aw = null; ae = null; ah = null;       // a cell depots per bit
    bw = null; be = null; bh = null;       // b cell depots per bit
    gw = null; ge = null; gt0 = null; gt1 = null;   // gate lane depots/taps per bit
    constructor() {}
}

// ---- helpers ----
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
function FibMain::ClearOrders(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    while (GSOrder.GetOrderCount(v) > 0) { if (!GSOrder.RemoveOrder(v, 0)) break; }
}
function FibMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(this.T(x, y));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
    GSTile.LevelTiles(this.T(x0, y0), this.T(x1, y1));
}

// ===================== CLOCK (verbatim hardened launch) =====================
function FibMain::BuildRect(x0, y0, x1, y1) {
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
function FibMain::SignalLoopOneWay() {
    for (local x = LX0 + 2; x < LX1; x += 3)
        GSRail.BuildSignal(this.T(x, LY0), this.T(x - 1, LY0), GSRail.SIGNALTYPE_NORMAL);
    for (local y = LY0 + 2; y < LY1; y += 3)
        GSRail.BuildSignal(this.T(LX1, y), this.T(LX1, y - 1), GSRail.SIGNALTYPE_NORMAL);
    for (local x = LX1 - 2; x > LX0; x -= 3)
        GSRail.BuildSignal(this.T(x, LY1), this.T(x + 1, LY1), GSRail.SIGNALTYPE_NORMAL);
    for (local y = LY1 - 2; y > LY0; y -= 3)
        GSRail.BuildSignal(this.T(LX0, y), this.T(LX0, y + 1), GSRail.SIGNALTYPE_NORMAL);
}
function FibMain::BuildClockStatic() {
    this.BuildRect(LX0, LY0, LX1, LY1);
    this.cdepot = this.T(CDX, LY0 - 1);
    GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
    this.SignalLoopOneWay();
}
function FibMain::NudgeEgress(v) {
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
function FibMain::LaunchOnce() {
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
        if (sawBottom && cx == LX0 && cy >= LY0 && cy <= LY1) return true;
        GSController.Sleep(5);
    }
    return false;
}
function FibMain::TeardownClock() {
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
function FibMain::LaunchClockConfirmed() {
    for (local t = 0; t < 4; t++) {
        if (this.LaunchOnce()) return true;
        this.Say("FF clkR" + t);
        for (local d = 0; d < 4 && !this.TeardownClock(); d++) GSController.Sleep(20);
        GSRail.BuildRailDepot(this.cdepot, this.T(CDX, LY0));
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_NE);
        GSRail.BuildRailTrack(this.T(CDX, LY0), GSRail.RAILTRACK_NW_SW);
        GSController.Sleep(20);
    }
    return false;
}
function FibMain::WaitClockEdge() {
    local waited = 0; local wasOff = false;
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

// ===================== REGISTER CELLS (one block-signal cell per bit) =====================
function FibMain::BuildCell(gy) {
    for (local x = BX; x < EASTX; x++)
        GSRail.BuildRailTrack(this.T(x, gy), GSRail.RAILTRACK_NE_SW);
    local wD = this.T(BX - 1, gy);
    GSRail.BuildRailDepot(wD, this.T(BX, gy));
    local eD = this.T(EASTX, gy);
    GSRail.BuildRailDepot(eD, this.T(EASTX - 1, gy));
    GSRail.BuildSignal(this.T(RSIGX, gy), this.T(RSIGX - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(TSIGX, gy), this.T(TSIGX - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    local hD = this.T(HX, gy - 1);
    GSRail.BuildRailDepot(hD, this.T(HX, gy));
    GSRail.BuildRailTrack(this.T(HX, gy), GSRail.RAILTRACK_NW_NE);
    return [wD, eD, hD];
}
function FibMain::BuildRegisters() {
    this.aw = []; this.ae = []; this.ah = []; this.aHold = [];
    this.bw = []; this.be = []; this.bh = []; this.bHold = [];
    for (local i = 0; i < NBITS; i++) {
        local ca = this.BuildCell(AY0 + i * RROWSTEP);
        this.aw.append(ca[0]); this.ae.append(ca[1]); this.ah.append(ca[2]); this.aHold.append(null);
        local cb = this.BuildCell(BY0 + i * RROWSTEP);
        this.bw.append(cb[0]); this.be.append(cb[1]); this.bh.append(cb[2]); this.bHold.append(null);
    }
}
function FibMain::IsHoldTok(v) {
    for (local j = 0; j < NBITS; j++) if (v == this.aHold[j] || v == this.bHold[j]) return true;
    return false;
}

// WRITE a bit cell to 1: park a HOLD train on HX of row gy (idempotent). register_gs Write1.
function FibMain::CellWrite1(holdArr, i, hD, gy) {
    local cur = holdArr[i];
    if (cur != null && GSVehicle.IsValidVehicle(cur) && this.Tx(cur) == HX && this.Ty(cur) == gy) return;
    local v = GSVehicle.BuildVehicle(hD, this.eng);
    this.built++;
    if (!GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.T(HX, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 50; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && this.Tx(v) == HX && this.Ty(v) == gy) { GSVehicle.StartStopVehicle(v); break; }
    }
    holdArr[i] = v;
}
// WRITE a bit cell to 0: remove the parked HOLD train (idempotent). register_gs Write0.
function FibMain::CellWrite0(holdArr, i, hD, gy) {
    local v = holdArr[i];
    if (v == null) return;
    if (GSVehicle.IsValidVehicle(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, hD, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSVehicle.ReverseVehicle(v);
        for (local w = 0; w < 40; w++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    holdArr[i] = null;
}
function FibMain::LiftHold(holdArr, i, hD, gy) {
    local v = holdArr[i];
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, hD, GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    GSVehicle.ReverseVehicle(v);
    for (local s = 0; s < 30; s++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
}
function FibMain::RestoreHold(holdArr, i, hD, gy) {
    local v = holdArr[i];
    if (v != null && GSVehicle.IsValidVehicle(v)) {
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.T(HX, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local w = 0; w < 40; w++) {
            GSController.Sleep(5);
            if (this.Tx(v) == HX && this.Ty(v) == gy) { GSVehicle.StartStopVehicle(v); return; }
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    holdArr[i] = null;
    this.CellWrite1(holdArr, i, hD, gy);
}

// READ one register bit via a fresh reader's RAW final x, FULLY disposing it. register_gs path.
// Returns 1 (held == bit 1), 0 (passed == bit 0), -1 (invalid read).
function FibMain::ReadCell(holdArr, i, wD, eD, hD, gy) {
    if (this.built >= 400) return -1;
    local v = GSVehicle.BuildVehicle(wD, this.eng);
    this.built++;
    if (!GSVehicle.IsValidVehicle(v)) return -1;
    GSOrder.AppendOrder(v, eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
    // EGRESS, hardened (one toggle per settle, the proven NudgeEgress discipline). The old loop
    // broke at Tx>=BX (true the instant the tile-center crosses to the first lane tile, while the
    // train may be at a standstill) and could strand a reader whose StartStop was dropped (the
    // run 1 "FF e" register-read failure). Keep nudging until the train has actually LEFT the depot.
    for (local r = 0; r < 18; r++) {
        if (!GSVehicle.IsValidVehicle(v)) break;
        if (!GSVehicle.IsStoppedInDepot(v)) break;
        GSVehicle.StartStopVehicle(v);
        GSController.Sleep(10);
    }
    local fx = BX - 1; local stable = 0; local lastx = -999;
    for (local s = 0; s < 22; s++) {
        GSController.Sleep(12);
        local nx = this.Tx(v);
        if (nx >= 0) fx = nx;
        if (fx >= TSIGX) break;   // clearly passed east of the read signal: HOLD empty (bit 0)
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v) && fx > RSIGX) break;
        if (fx >= BX && fx <= RSIGX) { if (fx == lastx) { stable++; if (stable >= 3) break; } else stable = 0; } else stable = 0;
        lastx = fx;
    }
    local q;
    if (fx > RSIGX) q = 0;
    else if (fx >= BX) q = 1;
    else q = -1;
    if (q == 1) {
        this.LiftHold(holdArr, i, hD, gy);
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local s = 0; s < 24; s++) { if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) break; GSController.Sleep(8); }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        this.RestoreHold(holdArr, i, hD, gy);
    } else {
        if (GSVehicle.IsValidVehicle(v) && !GSVehicle.IsStoppedInDepot(v)) {
            GSOrder.AppendOrder(v, eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
            for (local s = 0; s < 20; s++) { if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) break; GSController.Sleep(8); }
        }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    // safety: sell any non-clock, non-HOLD vehicle parked in a depot.
    foreach (vv, _ in GSVehicleList()) {
        if (vv == this.clock || this.IsHoldTok(vv)) continue;
        if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv)) GSVehicle.SellVehicle(vv);
    }
    return q;
}
function FibMain::ReadA(i) { return this.ReadCell(this.aHold, i, this.aw[i], this.ae[i], this.ah[i], AY0 + i * RROWSTEP); }
function FibMain::ReadB(i) { return this.ReadCell(this.bHold, i, this.bw[i], this.be[i], this.bh[i], BY0 + i * RROWSTEP); }

// ===================== THE NOR GATE LANE (one reusable 2-input NOR per bit row) =====================
function FibMain::BuildGateLane(gy) {
    for (local x = GBX; x < GEASTX; x++)
        GSRail.BuildRailTrack(this.T(x, gy), GSRail.RAILTRACK_NE_SW);
    local wD = this.T(GBX - 1, gy);
    GSRail.BuildRailDepot(wD, this.T(GBX, gy));
    local eD = this.T(GEASTX, gy);
    GSRail.BuildRailDepot(eD, this.T(GEASTX - 1, gy));
    GSRail.BuildSignal(this.T(GSIGX, gy), this.T(GSIGX - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(GTERMX, gy), this.T(GTERMX - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    local f0 = this.T(GTAP0, gy - 1); GSRail.BuildRailDepot(f0, this.T(GTAP0, gy)); GSRail.BuildRailTrack(this.T(GTAP0, gy), GSRail.RAILTRACK_NW_NE);
    local f1 = this.T(GTAP1, gy - 1); GSRail.BuildRailDepot(f1, this.T(GTAP1, gy)); GSRail.BuildRailTrack(this.T(GTAP1, gy), GSRail.RAILTRACK_NW_NE);
    return [wD, eD, f0, f1];
}
function FibMain::BuildGates() {
    this.gw = []; this.ge = []; this.gt0 = []; this.gt1 = [];
    for (local i = 0; i < NBITS; i++) {
        local g = this.BuildGateLane(GY0 + i * RROWSTEP);
        this.gw.append(g[0]); this.ge.append(g[1]); this.gt0.append(g[2]); this.gt1.append(g[3]);
    }
}

// Park a train on a gate tap from its feeder depot (re-materialise an input bit). Returns a token
// that is CONFIRMED resting on the tap (its presence is the input bit), or null on failure. A tap
// that does not land ON its tile would silently make the NOR read the input as absent (the SC2
// fragility), so we confirm placement and retry; on persistent failure we sell the dud and return
// null so the caller's gate read fails cleanly (flagged) rather than computing a wrong bit.
function FibMain::ParkGateTap(fD, tx, gy) {
    for (local attempt = 0; attempt < 3; attempt++) {
        local v = GSVehicle.BuildVehicle(fD, this.eng);
        this.built++;
        if (!GSVehicle.IsValidVehicle(v)) { GSController.Sleep(8); continue; }
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.T(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
        // EGRESS: keep nudging (one toggle per settle, the hardened-launch discipline) until the
        // train has actually LEFT the feeder depot. A single StartStop can be dropped/queued, which
        // left the train in the depot and made the tap read absent (the FF g failure). Nudge with a
        // settle between toggles so a queued command is never double-fired.
        for (local r = 0; r < 14; r++) {
            if (!GSVehicle.IsValidVehicle(v)) break;
            if (!GSVehicle.IsStoppedInDepot(v)) break;
            GSVehicle.StartStopVehicle(v);
            GSController.Sleep(10);
        }
        // LANDING: wait (longer, the train must travel from the depot down onto the tap and stop)
        // until it rests ON the tap tile, then stop it dead there. The bit is now present.
        for (local w = 0; w < 40; w++) {
            GSController.Sleep(6);
            if (GSVehicle.IsValidVehicle(v) && this.Tx(v) == tx && this.Ty(v) == gy) { GSVehicle.StartStopVehicle(v); break; }
        }
        if (GSVehicle.IsValidVehicle(v) && this.Tx(v) == tx && this.Ty(v) == gy) return v;  // confirmed on tap
        // did not land on the tap: dispose this dud and retry.
        if (GSVehicle.IsValidVehicle(v)) {
            this.ClearOrders(v);
            GSOrder.AppendOrder(v, fD, GSOrder.OF_NON_STOP_INTERMEDIATE);
            if (!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
            GSVehicle.ReverseVehicle(v);
            for (local w = 0; w < 24; w++) { GSController.Sleep(6); if (GSVehicle.IsStoppedInDepot(v)) break; }
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        }
    }
    return null;
}
// Remove a parked tap train by driving it EAST through the lane to the gate east depot and selling
// it (a clean through-path, the same way a reader exits). The earlier reverse-into-feeder approach
// did not reliably back the tap off its tile, leaving it in the block to hold the next gate's reader
// (the c00=45 jam). Driving east past the terminating signal into the depot is robust. The tap is a
// manually-stopped train, so it needs a StartStop to resume; nudge until it leaves its tile.
function FibMain::ClearGateTap(v, i) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.ge[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
    // resume the manually-stopped tap (nudge until it actually moves off its tile).
    local startx = this.Tx(v); local starty = this.Ty(v);
    for (local r = 0; r < 10; r++) {
        if (!GSVehicle.IsValidVehicle(v)) return;
        if (!(this.Tx(v) == startx && this.Ty(v) == starty)) break;   // moving
        GSVehicle.StartStopVehicle(v);
        GSController.Sleep(10);
    }
    for (local w = 0; w < 36; w++) { GSController.Sleep(10); if (!GSVehicle.IsValidVehicle(v) || GSVehicle.IsStoppedInDepot(v)) break; }
    if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
}

// NOR(x, y): the PHYSICAL block-signal NOR on gate lane i. Park bits x,y on the two taps, run a
// fresh reader, return its raw PASS/HOLD outcome: 1 iff it PASSED (both taps empty) else 0,
// judged from the RAW reader x (> GSIGX). Returns -1 on a failed reader (caller treats as break).
// This is exactly the proven norgate_gs NOR; the output bit is the raw reader position.
function FibMain::Nor(i, x, y) {
    if (this.built >= 400) return -1;
    local gy = GY0 + i * RROWSTEP;
    // PRE-READ BLOCK DRAIN. The gate lane is REUSED for all 9 NORs of a bit, so a leftover reader
    // or tap train from the previous gate would make this NOR's reader wrongly HELD (reading an
    // occupied block when the inputs say empty). Before parking the inputs, sweep the whole gate
    // lane row and the two tap tiles clear of any non-clock, non-HOLD vehicle. Any vehicle whose
    // tile is on this gate row (or its tap feeder rows) is sold; held register tokens and the
    // clock are skipped. This guarantees the block reflects ONLY this gate's parked inputs.
    foreach (vv, _ in GSVehicleList()) {
        if (vv == this.clock || this.IsHoldTok(vv)) continue;
        if (!GSVehicle.IsValidVehicle(vv)) continue;
        local vx = this.Tx(vv); local vy = this.Ty(vv);
        local onThisGate = (vy == gy && vx >= GBX - 1 && vx <= GEASTX)
                        || (vy == gy - 1 && (vx == GTAP0 || vx == GTAP1));
        if (!onThisGate) continue;
        if (GSVehicle.IsStoppedInDepot(vv)) { GSVehicle.SellVehicle(vv); continue; }
        // on the lane and not in a depot (a held reader or a manually-parked tap train): order it
        // into the east depot. A held reader auto-resumes once the block clears; a manually-parked
        // train is restarted by one StartStop only if it is not already moving (checked by a short
        // position-stability probe so a moving train is never re-stopped).
        this.ClearOrders(vv);
        GSOrder.AppendOrder(vv, this.ge[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
        local px = this.Tx(vv); GSController.Sleep(6);
        if (GSVehicle.IsValidVehicle(vv) && this.Tx(vv) == px && !GSVehicle.IsStoppedInDepot(vv))
            GSVehicle.StartStopVehicle(vv);   // not moving -> resume
        for (local s = 0; s < 22; s++) { if (!GSVehicle.IsValidVehicle(vv) || GSVehicle.IsStoppedInDepot(vv)) break; GSController.Sleep(12); }
        if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv)) GSVehicle.SellVehicle(vv);
    }
    local p0 = (x == 1) ? this.ParkGateTap(this.gt0[i], GTAP0, gy) : null;
    local p1 = (y == 1) ? this.ParkGateTap(this.gt1[i], GTAP1, gy) : null;
    // If an input that SHOULD be present failed to park, the NOR would read it as absent and
    // compute a wrong bit. Fail the read cleanly instead (the caller breaks and the term is
    // flagged), after clearing any tap that did land.
    if ((x == 1 && p0 == null) || (y == 1 && p1 == null)) {
        if (p0 != null) this.ClearGateTap(p0, i);
        if (p1 != null) this.ClearGateTap(p1, i);
        return -1;
    }
    GSController.Sleep(6);
    local v = GSVehicle.BuildVehicle(this.gw[i], this.eng);
    this.built++;
    local out = -1;
    if (GSVehicle.IsValidVehicle(v)) {
        GSOrder.AppendOrder(v, this.ge[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
        // EGRESS (norgate proven): nudge until NOT stopped-in-depot (the train is actually moving),
        // not merely until Tx>=GBX. Tx>=GBX reads true the instant the tile-center crosses to the
        // first lane tile, while the train may still be at a standstill there; breaking then leaves
        // a stopped reader that the (formerly too-short) settle misread as held. The fix is this
        // proven egress plus the LONGER settle below (Sleep(16) x 20 ~= 10s, enough for the reader
        // to travel 40->46 at train speed); the prior Sleep(8) x 16 ~= 4s was not enough and made
        // every NOR misread as held=0. Verified in scenarios/selffib_gs/diag.nut: NOR(0,0)->x52
        // (pass=1), NOR(1,0)->x45 (held=0).
        // EGRESS, hardened (NudgeEgress discipline): fire ONE start toggle per SETTLE so a queued
        // StartStop is never double-fired, and give a GENEROUS budget. A reader that fails to leave
        // its depot (stuck at GBX-1) was a recurring failure (DG 00=39); this one-toggle-per-settle
        // loop is the proven fix from the clock launch.
        for (local r = 0; r < 18; r++) {
            if (!GSVehicle.IsValidVehicle(v)) break;
            if (!GSVehicle.IsStoppedInDepot(v)) break;     // moving / left the depot
            GSVehicle.StartStopVehicle(v);
            GSController.Sleep(10);
        }
        local fx = GBX - 1; local stable = 0; local lastx = -999;
        for (local s = 0; s < 20; s++) {
            GSController.Sleep(16);
            local nx = this.Tx(v);
            if (nx >= 0) fx = nx;
            // PASSED: the reader is past the gate signal. Once it is clearly east of GSIGX (at the
            // terminator or beyond) it has passed the NOR (output 1); exit early instead of waiting
            // for it to reach the depot, which saves ~5s per passing gate across the many reads.
            if (fx >= GTERMX) break;
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v) && fx > GSIGX) break;
            if (fx >= GBX && fx <= GSIGX) { if (fx == lastx) { stable++; if (stable >= 3) break; } else stable = 0; } else stable = 0;
            lastx = fx;
        }
        if (fx > GSIGX) out = 1;
        else if (fx >= GBX) out = 0;
        else out = -1;
        // DISPOSE the reader and CONFIRM the lane ends EMPTY (the reuse-jam fix). If held (out 0),
        // first clear the taps so the gate signal greens, then DRIVE the reader to the east depot
        // and wait LONG ENOUGH for it to travel the full lane (a held reader at x~42 must roll
        // ~10 tiles east, which the earlier ~6s wait did not allow, leaving it on the lane to jam
        // the next gate read as occupied -> the FF g failure). Re-order it east explicitly and
        // poll generously; then sell it from the depot.
        if (out == 0) {
            if (p0 != null) { this.ClearGateTap(p0, i); p0 = null; }
            if (p1 != null) { this.ClearGateTap(p1, i); p1 = null; }
            this.ClearOrders(v);
            GSOrder.AppendOrder(v, this.ge[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
            for (local s = 0; s < 40; s++) { if (!GSVehicle.IsValidVehicle(v) || GSVehicle.IsStoppedInDepot(v)) break; GSController.Sleep(10); }
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        } else {
            for (local s = 0; s < 28; s++) { if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) break; GSController.Sleep(10); }
            if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        }
    }
    // clear any still-parked taps.
    if (p0 != null) this.ClearGateTap(p0, i);
    if (p1 != null) this.ClearGateTap(p1, i);
    // CONFIRM the gate lane is now EMPTY of any non-clock, non-HOLD vehicle (drive stragglers to
    // the east depot and sell). This guarantees the next gate read sees an empty block.
    for (local pass = 0; pass < 2; pass++) {
        local anyLeft = false;
        foreach (vv, _ in GSVehicleList()) {
            if (vv == this.clock || this.IsHoldTok(vv) || !GSVehicle.IsValidVehicle(vv)) continue;
            local vx = this.Tx(vv); local vy = this.Ty(vv);
            local onThisGate = (vy == gy && vx >= GBX - 1 && vx <= GEASTX)
                            || (vy == gy - 1 && (vx == GTAP0 || vx == GTAP1));
            if (GSVehicle.IsStoppedInDepot(vv)) { GSVehicle.SellVehicle(vv); continue; }
            if (!onThisGate) continue;
            anyLeft = true;
            this.ClearOrders(vv);
            GSOrder.AppendOrder(vv, this.ge[i], GSOrder.OF_NON_STOP_INTERMEDIATE);
            local px = this.Tx(vv); GSController.Sleep(6);
            if (GSVehicle.IsValidVehicle(vv) && this.Tx(vv) == px && !GSVehicle.IsStoppedInDepot(vv)) GSVehicle.StartStopVehicle(vv);
            for (local s = 0; s < 30; s++) { if (!GSVehicle.IsValidVehicle(vv) || GSVehicle.IsStoppedInDepot(vv)) break; GSController.Sleep(10); }
            if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv)) GSVehicle.SellVehicle(vv);
        }
        if (!anyLeft) break;
    }
    return out;
}

// FULL ADDER on bit i from the NOR gate lane: EVERY gate is a real block-signal NOR read at a raw
// reader position, and each gate's inputs are re-materialised from the PRIOR raw gate reads (or the
// raw held register bits a,b and the raw carry c). So the n-values are NOT computed in Squirrel:
// n1 is the raw read of NOR(a,b), n2 the raw read of NOR(a, [n1's raw read]), and so on, with sum
// and cout the raw reads of the final two NORs. The only Squirrel role is WIRING (which raw output
// feeds which next-gate tap), exactly the role norchain's coupling spur plays in hardware. This is
// the honest, genuinely-computing adder; it is also the expensive one (9 physical reads/bit), which
// is why the run is low-yield by design.
//
// The 9-NOR netlist (checked exhaustively in Python, all 8 rows == a+b+c):
//   n1=NOR(a,b); n2=NOR(a,n1); n3=NOR(b,n1); n4=NOR(n2,n3)=a^b
//   n5=NOR(n4,c); n6=NOR(n4,n5); n7=NOR(c,n5); sum=NOR(n6,n7)=a^b^c; cout=NOR(n5,n1)=maj(a,b,c)
// Returns [sum, cout] each in {0,1}, or [-1,-1] on a failed gate read (caller breaks).
function FibMain::FullAdd(i, a, b, c) {
    local n1 = this.Nor(i, a, b);          if (n1 < 0) return [-1, -1];
    local n2 = this.Nor(i, a, n1);         if (n2 < 0) return [-1, -1];
    local n3 = this.Nor(i, b, n1);         if (n3 < 0) return [-1, -1];
    local n4 = this.Nor(i, n2, n3);        if (n4 < 0) return [-1, -1];   // a XOR b
    local n5 = this.Nor(i, n4, c);         if (n5 < 0) return [-1, -1];
    local n6 = this.Nor(i, n4, n5);        if (n6 < 0) return [-1, -1];
    local n7 = this.Nor(i, c, n5);         if (n7 < 0) return [-1, -1];
    local sum  = this.Nor(i, n6, n7);      if (sum  < 0) return [-1, -1]; // a XOR b XOR c, raw read
    local cout = this.Nor(i, n5, n1);      if (cout < 0) return [-1, -1]; // majority(a,b,c), raw read
    return [sum, cout];
}

function FibMain::Start() {
    if (this.terms != null) {
        while (true) { this.Say("FF " + this.terms); GSController.Sleep(74); }
    }
    if (this.started) {
        while (true) { this.Say("FF REENTRY"); GSController.Sleep(74); }
    }
    this.started = true;
    try { this.Run(); }
    catch (e) { while (true) { this.Say("FF ERR"); GSController.Sleep(74); } }
}

function FibMain::Run() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("FF build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    for (local w = 0; w < 40 && this.eng == null; w++) { GSController.Sleep(10); this.eng = this.PickEngine(rt); }
    GSController.Sleep(20);

    // flat canvas: clock loop, both register banks, and the gate bank, all disjoint rows.
    this.Prepare(LX0 - 2, LY0 - 2, LX1 + 2, LY1 + 2);
    this.Prepare(BX - 2, AY0 - 2, EASTX + 1, AY0 + NBITS * RROWSTEP + 1);
    this.Prepare(BX - 2, BY0 - 2, EASTX + 1, BY0 + NBITS * RROWSTEP + 1);
    this.Prepare(GBX - 2, GY0 - 2, GEASTX + 1, GY0 + NBITS * RROWSTEP + 1);

    // CLOCK FIRST (most reliable launch as the first vehicle build).
    this.BuildClockStatic();
    this.Say("FF clk..");
    local ok = this.LaunchClockConfirmed();
    if (!ok) { while (true) { this.Say("CKFAIL"); GSController.Sleep(74); } }
    this.Say("FF clkOK");

    this.BuildRegisters();
    this.BuildGates();
    this.Say("FF built");

    // INITIALISE the window a=0, b=1.
    for (local i = 0; i < NBITS; i++) this.CellWrite0(this.aHold, i, this.ah[i], AY0 + i * RROWSTEP);
    this.CellWrite1(this.bHold, 0, this.bh[0], BY0);
    for (local i = 1; i < NBITS; i++) this.CellWrite0(this.bHold, i, this.bh[i], BY0 + i * RROWSTEP);

    // ---- SELF-FEEDING CLOCK EDGES ----
    // 2-bit registers hold 0..3, so the cleanly self-fed output is 1,1,2,3 (b reaches 3; the next
    // term 5 would overflow a 2-bit b, the honest stopping point). Each edge is a full genuine
    // 2-bit NOR-full-adder (18 physical gate reads) plus register reads, so a full clean edge is
    // slow and low-yield. NEDGES = 4 targets 1,1,2,3; the run reports how many actually self-fed.
    local NEDGES = 4;
    local out = "";        // space-separated output terms (next read each edge)
    local pmin = 9999;
    for (local k = 0; k < NEDGES; k++) {
        local waited = this.WaitClockEdge();
        if (waited < pmin) pmin = waited;

        // (1) READ a and b bit-by-bit from the held registers (raw reader x per bit).
        local aBits = []; local bBits = []; local fail = false;
        for (local i = 0; i < NBITS; i++) {
            local qa = -1; for (local rd = 0; rd < 2 && qa < 0; rd++) qa = this.ReadA(i);
            local qb = -1; for (local rd = 0; rd < 2 && qb < 0; rd++) qb = this.ReadB(i);
            if (qa < 0 || qb < 0) { fail = true; aBits.append(0); bBits.append(0); }
            else { aBits.append(qa); bBits.append(qb); }
        }
        if (fail) { out += (out == "" ? "" : " ") + "e"; break; }
        local av = 0; local bv = 0;
        for (local i = 0; i < NBITS; i++) { av = av + (aBits[i] << i); bv = bv + (bBits[i] << i); }
        this.Say("e" + k + " rd a" + av + " b" + bv);   // progress: registers read

        // (2) COMPUTE next = a + b with the NOR full adder, ripple carry, sum bits raw-read.
        local sumBits = []; local carry = 0; local gateFail = false;
        for (local i = 0; i < NBITS; i++) {
            local sc = this.FullAdd(i, aBits[i], bBits[i], carry);
            if (sc[0] < 0) { gateFail = true; break; }
            sumBits.append(sc[0]);
            carry = sc[1];
            this.Say("e" + k + " add" + i + " s" + sc[0] + " c" + sc[1]);  // progress: bit i added
        }
        if (gateFail) { out += (out == "" ? "" : " ") + "g"; break; }
        // the top sum bit (SBITS-1) is the final carry out, also a raw gate read.
        local nextv = 0;
        for (local i = 0; i < NBITS; i++) nextv = nextv + (sumBits[i] << i);
        nextv = nextv + (carry << NBITS);

        // (4) READ OUT next.
        out += (out == "" ? "" : " ") + nextv;

        // (3) SHIFT the window: a <- b, b <- next (GS-mediated writes, the honest boundary).
        for (local i = 0; i < NBITS; i++) {
            local gyA = AY0 + i * RROWSTEP;
            if (bBits[i] == 1) this.CellWrite1(this.aHold, i, this.ah[i], gyA);
            else this.CellWrite0(this.aHold, i, this.ah[i], gyA);
        }
        for (local i = 0; i < NBITS; i++) {
            local gyB = BY0 + i * RROWSTEP;
            local nb_bit = (nextv >> i) & 1;
            if (nb_bit == 1) this.CellWrite1(this.bHold, i, this.bh[i], gyB);
            else this.CellWrite0(this.bHold, i, this.bh[i], gyB);
        }

        local nt = GSVehicleList().Count();
        this.Say("e" + k + " a" + av + " b" + bv + " s" + nextv + " n" + nt);
        GSController.Sleep(6);
    }

    this.terms = out;
    this.HoldResult(out, pmin);
}

function FibMain::HoldResult(out, pmin) {
    local a = "FF " + out;
    local b = "FF " + out + " p" + pmin;
    while (true) { this.Say(a); GSController.Sleep(40); this.Say(b); GSController.Sleep(40); }
}

function FibMain::Save() { return { terms = this.terms }; }
function FibMain::Load(version, data) {
    if ("terms" in data && data.terms != null) this.terms = data.terms;
}
