/*
 * facombo: the SINGLE-COMBO 1-bit FULL ADDER on real trains. Builds ONE combo's worth of network
 * (NOT the 8-copy mega-build): the bridged SUM + the majority CARRY for ONE (a,b,cin) selected by the
 * `combo` GS setting (GSController.GetSetting("combo"), 0..7 = 000..111). About 16 gates + 6 bridges,
 * so it is small, fast and reliable. The gate/bridge/freeze code is the HARDENED fulladder_gs code,
 * REUSED VERBATIM (RunG3Freeze / NudgeEgress / ParkInput / BuildOneBridge pre-checks); only the
 * top-level build/run loop differs (one band, not eight).
 *
 *   SUM  = parity(a,b,cin) = XOR( XOR(a,b), cin )   (the fasum two-stacked-bridged-XOR, rows DY 0..43)
 *          read from the RAW Y reader x (x > Y_SIG=50 => sum 1). Expected over 8 combos 0,1,1,0,1,0,0,1.
 *   COUT = majority(a,b,cin) = NOR3(NOR(a,b),NOR(a,cin),NOR(b,cin))   (the proven fulladder_cout
 *          4-lane NOR network, rows DY COUT+0..COUT+9 BELOW the sum in the same band)
 *          read from the RAW gm reader x (x > GM_SIG=40 => cout 1). Expected over 8 combos 0,0,0,1,0,1,1,1.
 *
 * Both networks are INDEPENDENT fixed NOR networks sharing only the primary inputs a,b,cin. Outputs
 * are RAW reader x only; nothing computed in Squirrel. Readout: "c<abc> s<x> m<x>", then the latched
 * "FA<Y_SIG> <sum x>" / "FC<GM_SIG> <cout x>" streamed in turn (each under the ~31-char name limit).
 */

// ===================== SUM network columns (fasum / xorsum1 EXACT geometry) =====================
A_BX <- 30; A_SIG <- 36; A_TA <- 37; A_TB <- 38; A_SIGT <- 39; A_CPL <- 40; A_EAST <- 48;
B_BX <- 32; B_SIG <- 38; B_TA <- 39; B_TN <- 40; B_SIGT <- 41; B_CPL <- 42; B_EAST <- 50;
// RECONVERGENT-FREEZE FIX (ported from xorsum1, PROVEN): g3's coupling block is the WIDE through block
// [C_CPL..C_TERM2]=[45..50] (was the narrow [45..46]). The g3->g4 spur drops at column 45; the whole
// block [45..50] is ONE signal block connected to that spur, so a passing g3 frozen ANYWHERE in [45..50]
// occupies g4's input through the bridge. The old 2-tile window let the ASYNC StartStop freeze DRIFT g3
// past C_TERM2=46 into a block DISCONNECTED from the spur (g4 read empty, wrongly passed = the c00 flake).
// Widening absorbs the drift; nothing else uses g3's row east of 44 so it is safe (C_EAST 52->54).
C_BX <- 35; C_SIG <- 41; C_T2 <- 42; C_T3 <- 43; C_SIGT <- 44; C_CPL <- 45; C_TERM2 <- 50; C_EAST <- 54;
D_BX <- 37; D_SIG <- 38; D_TB <- 40; D_TN <- 41; D_SIGT <- 42; D_CPL <- 43; D_TERM2 <- 47; D_EAST <- 54;
E_BX <- 36; E_SIG <- 37; E_TA <- 38; E_TB <- 39; E_SIGT <- 40; E_CPL <- 41; E_TERM2 <- 47; E_EAST <- 54;
F_BX <- 42; F_SIG <- 44; F_TN <- 45; F_SIGT <- 49; F_CPL <- 50; F_EAST <- 56;   // g4 -> h at col 50

DY_A <- 0; DY_B <- 3; DY_C <- 6; DY_D <- 9; DY_E <- 13; DY_F <- 16;   // XOR1 rows

NHa_BX <- 44; NHa_SIG <- 48; NHa_TH <- 50; NHa_SIGT <- 51; NHa_CPL <- 52; NHa_EAST <- 60;
// NHb is the XOR2 reconvergent bridged driver (NOR(h)) whose frozen reader must occupy Q's input
// THROUGH the bridged NHb->Q spur (column NHb_CPL=53). Its coupling block [NHb_CPL..NHb_TERM2] is
// WIDENED 54->56 (the same drift-absorption fix as g3's), so a passing NHb frozen anywhere in [53..56]
// still occupies the column-53 spur; the freeze drift can no longer carry it past the block.
NHb_BX <- 44; NHb_SIG <- 48; NHb_TH <- 50; NHb_SIGT <- 51; NHb_CPL <- 53; NHb_TERM2 <- 56; NHb_EAST <- 60;
HH_BX <- 46; HH_SIG <- 49; HH_TNHA <- 52; HH_SIGT <- 55; HH_CPL <- 56; HH_EAST <- 64;
P_BX  <- 46; P_SIG  <- 49; P_TCIN <- 51; P_THH <- 56; P_SIGT <- 57; P_CPL <- 58; P_EAST <- 66;
Y_BX  <- 46; Y_SIG  <- 50; Y_TP <- 58; Y_TQ <- 59; Y_SIGT <- 60; Y_CPL <- 61; Y_EAST <- 68;
Q_BX  <- 46; Q_SIG  <- 50; Q_TNC <- 52; Q_TNHB <- 53; Q_SIGT <- 54; Q_CPL <- 59; Q_TERM2 <- 60; Q_EAST <- 66;
NC_BX <- 44; NC_SIG <- 49; NC_TCIN <- 50; NC_SIGT <- 51; NC_CPL <- 52; NC_EAST <- 60;

DY_NHb <- 20; DY_NHa <- 23; DY_HH <- 27; DY_P <- 31; DY_Y <- 35; DY_Q <- 39; DY_NC <- 43;

// ===================== CARRY network columns (fulladder_cout EXACT geometry) =====================
R1_BX <- 31; R1_SIG <- 37; R1_TA <- 38; R1_TB <- 39; R1_SIGT <- 41; R1_CPL <- 42; R1_EAST <- 48;
GM_BX <- 34; GM_SIG <- 40; GM_T1 <- 42; GM_T2 <- 43; GM_T3 <- 50; GM_SIGT <- 51; GM_EAST <- 57;
R2_BX <- 32; R2_SIG <- 38; R2_TA <- 39; R2_TC <- 40; R2_SIGT <- 42; R2_CPL <- 43; R2_EAST <- 49;
R3_BX <- 39; R3_SIG <- 45; R3_TB <- 46; R3_TC <- 47; R3_SIGT <- 49; R3_CPL <- 50; R3_TERM2 <- 51; R3_EAST <- 56;

// CARRY network sits BELOW the sum in the same combo band: cout DY = COUT + the cout-internal dy.
COUT <- 48;                          // offset of the carry sub-band below the sum top (sum ends DY43)
DY_R1 <- COUT + 0; DY_GM <- COUT + 3; DY_R2 <- COUT + 6; DY_R3 <- COUT + 9;   // 48,51,54,57

BASE <- 30;   // the SINGLE combo's SUM g0a row (one band only, ends at DY_R3=57 -> map 8 is ample)

// COMBO SELECTION. The combo 0..7 = (a,b,cin) is chosen PER RUN. The primary channel is a per-run
// source edit: the runner (tools/run_facombo.py) rewrites the COMBO_SEL line below before installing
// this main.nut into the game dir, so each fresh server builds exactly ONE selected band. (The GS
// `combo` setting in info.nut is declared too, but the [game_scripts.facombo] cfg subsection is NOT
// applied to a dedicated-server newgame GS here, GetSetting returns the default 0, verified, so the
// source constant is the reliable selector and takes precedence.)
COMBO_SEL <- 0;   // RUNNER-REWRITTEN: 0..7 = abc 000..111

class FaComboMain extends GSController {
    company = null; eng = null; allbr = true;
    // OCCUPANCY GUARD (the combo-111 heavy-combo fix). Each gate's protected input block is one rail
    // row [sig..sigt]. A block-signal NOR reads "ANY input present in the block" (the block is occupied
    // => the signal is red => the reader is held), so a SINGLE parked train fully implements the input
    // for a multi-input gate. The all-ones combo 111 is the only case that drives BOTH inputs of the
    // shared gates (g0a,g0b,R1,R2,R3) present at once; parking a SECOND train into a block the first
    // train already occupies can NEVER succeed (the second train is stopped at the depot exit by the
    // red signal of the occupied block) and burns ParkInput's full ~88s 4-attempt budget each time, so
    // five redundant double-parks blow the run past the timeout and the readout never latches (the
    // documented "FA built1 b1" freeze). occRows records the rows that already hold a parked input;
    // ParkOcc skips a redundant second park on an already-occupied row (a fast no-op, logic identical).
    occRows = null;
    constructor() { this.occRows = {}; }
}

function FaComboMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function FaComboMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function FaComboMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function FaComboMain::Say(s) { GSCompany.SetName(s); }
// Prepare a flat strip [x0..x1] x [y0..y1]. CHUNKED + yielded (the same fix as fulladder_gs): a single
// LevelTiles over a big rectangle hangs the dedicated server's tick loop, so demolish + level in
// horizontal strips of <= STRIP rows, each its own bounded command with a yield. One band is small so
// this is fast, but the chunking is kept for safety. Progress reported via `tag`.
function FaComboMain::Prepare(x0, y0, x1, y1, tag) {
    local STRIP = 24;
    for (local sy = y0; sy <= y1; sy += STRIP) {
        local ey = sy + STRIP - 1; if (ey > y1) ey = y1;
        for (local x = x0; x <= x1; x++) {
            for (local y = sy; y <= ey; y++)
                GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
            GSController.Sleep(1);
        }
        GSTile.LevelTiles(GSMap.GetTileIndex(x0, sy), GSMap.GetTileIndex(x1, ey));
        GSController.Sleep(2);
        GSTile.LevelTiles(GSMap.GetTileIndex(x0, sy), GSMap.GetTileIndex(x1, ey));
        GSController.Sleep(1);
        if (tag != null) this.Say(tag + " prep" + ((ey - y0) * 100 / (y1 - y0)));
    }
}
function FaComboMain::SignalVerified(sx, gy) {
    local t = GSMap.GetTileIndex(sx, gy);
    local f = GSMap.GetTileIndex(sx - 1, gy);
    for (local i = 0; i < 8; i++) {
        if (GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE) return true;
        GSRail.BuildSignal(t, f, GSRail.SIGNALTYPE_NORMAL);
        GSController.Sleep(2);
    }
    return GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE;
}
function FaComboMain::BuildLane(bx, eastx, gy, sigx, sigtx, term2x) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
    GSController.Sleep(1);
    local wd = GSMap.GetTileIndex(bx - 1, gy);
    GSRail.BuildRailDepot(wd, GSMap.GetTileIndex(bx, gy));
    local ed = GSMap.GetTileIndex(eastx, gy);
    GSRail.BuildRailDepot(ed, GSMap.GetTileIndex(eastx - 1, gy));
    this.SignalVerified(sigx, gy);
    this.SignalVerified(sigtx, gy);
    if (term2x > 0) this.SignalVerified(term2x, gy);
    return { wd = wd, ed = ed };
}
function FaComboMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}
function FaComboMain::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}
// Ensure the E-W lane (under-rail) exists on (cplx,ly): the bridge carries the spur OVER it. The
// under-rail is the load-bearing tile the bridge crosses; if it is missing the crossed gate lane is
// cut, so this is confirmed RIGHT BEFORE every BuildBridge, not just once.
function FaComboMain::EnsureUnderRail(cplx, ly) {
    for (local i = 0; i < 12 && !GSRail.IsRailTile(GSMap.GetTileIndex(cplx, ly)); i++) {
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, ly), GSRail.RAILTRACK_NE_SW);
        GSController.Sleep(3);
    }
    return GSRail.IsRailTile(GSMap.GetTileIndex(cplx, ly));
}
// A ramp tile (head=ly-1, tail=ly+1) MUST be EMPTY of rail before BuildBridge: GSBridge.BuildBridge
// builds its OWN ramps there, and a stray rail tile (a leftover vertical spur piece, or a partial
// ramp from a dropped earlier attempt) makes the build silently fail. Demolish until the tile is not
// a rail tile (and not a bridge end). Returns true once the tile is clear.
function FaComboMain::ClearRamp(t) {
    for (local i = 0; i < 12; i++) {
        if (GSBridge.IsBridgeTile(t)) GSBridge.RemoveBridge(t);
        else if (GSRail.IsRailTile(t)) GSTile.DemolishTile(t);
        else return true;
        GSController.Sleep(3);
    }
    return !GSRail.IsRailTile(t) && !GSBridge.IsBridgeTile(t);
}
// HARDENED length-3 N-S bridge in column cplx over lane row ly (verbatim from fulladder_gs). The
// bridge build flaked intermittently (b0) under three diagnosed causes, each addressed here:
//   (1) RAMP NOT EMPTY. ClearRamp confirms BOTH ramp tiles empty IMMEDIATELY before each BuildBridge.
//   (2) UNDER-RAIL MISSING. EnsureUnderRail confirmed RIGHT BEFORE each BuildBridge.
//   (3) TRANSIENT QUEUE DROP. Retry with a settle, BOTH-ENDS IsBridgeTile verify, and a FULL COLUMN
//       TEARDOWN between rounds so a partial/failed state is fully cleared before the next round.
function FaComboMain::BuildOneBridge(cplx, ly) {
    local head = GSMap.GetTileIndex(cplx, ly - 1);
    local tail = GSMap.GetTileIndex(cplx, ly + 1);
    local under = GSMap.GetTileIndex(cplx, ly);
    local len = GSMap.DistanceManhattan(head, tail) + 1;
    for (local round = 0; round < 7; round++) {
        if (GSBridge.IsBridgeTile(head) && GSBridge.IsBridgeTile(tail)) return true;
        // pre-conditions, confirmed immediately before the build attempts this round:
        this.ClearRamp(head);            // ramp tiles EMPTY (cause 1)
        this.ClearRamp(tail);
        this.EnsureUnderRail(cplx, ly);  // under-rail PRESENT (cause 2)
        GSController.Sleep(3);           // drain the queue before the build (cause 3)
        for (local i = 0; i < 8; i++) {
            if (GSBridge.IsBridgeTile(head) && GSBridge.IsBridgeTile(tail)) return true;
            local types = GSBridgeList_Length(len);
            if (!types.IsEmpty()) GSBridge.BuildBridge(GSVehicle.VT_RAIL, types.Begin(), head, tail);
            GSController.Sleep(4);
        }
        if (GSBridge.IsBridgeTile(head) && GSBridge.IsBridgeTile(tail)) return true;
        // FULL COLUMN TEARDOWN: clear any partial bridge + the ramps + the under-tile, rebuild the
        // under-rail, longer settle, so the next round starts from a clean column (cause 3).
        if (GSBridge.IsBridgeTile(head)) GSBridge.RemoveBridge(head);
        if (GSBridge.IsBridgeTile(tail)) GSBridge.RemoveBridge(tail);
        GSController.Sleep(2);
        GSTile.DemolishTile(head);
        GSTile.DemolishTile(under);
        GSTile.DemolishTile(tail);
        GSController.Sleep(6);
        this.EnsureUnderRail(cplx, ly);
        GSController.Sleep(6);
    }
    return GSBridge.IsBridgeTile(head) && GSBridge.IsBridgeTile(tail);
}
function FaComboMain::BuildBridgedSpur(cplx, gya, gyb, lys) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++) {
        local span = false;
        foreach (ly in lys) if (y >= ly - 1 && y <= ly + 1) span = true;
        if (span) continue;
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    }
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
    local ok = true;
    foreach (ly in lys) ok = this.BuildOneBridge(cplx, ly) && ok;
    return ok;
}
// ---- SHARED EGRESS HARDENING (the proven main_clocked.nut NudgeEgress pattern, see xorsum1) ----
// Fire EXACTLY ONE start toggle per SETTLE (StartStopVehicle is async/queued; a tight re-poll
// double-toggles and re-stops the train, the documented raw x = -1 / wrongly-absent-input flake).
// One-shot, settle-verified egress for a vehicle whose depot tile is (dx,dy).
function FaComboMain::NudgeEgress(v, dx, dy) {
    for (local r = 0; r < 40; r++) {
        if (!GSVehicle.IsValidVehicle(v)) return false;
        local cx = this.Tx(v); local cy = this.Ty(v);
        if (cx >= 0 && !(cx == dx && cy == dy) && !GSVehicle.IsStoppedInDepot(v)) return true;
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(10);
    }
    return (GSVehicle.IsValidVehicle(v) && !GSVehicle.IsStoppedInDepot(v));
}
// Dispose a stray input/reader (see xorsum1::Scrap): home to depot d then sell; never sell mid-track.
function FaComboMain::Scrap(v, d) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    if (GSVehicle.IsStoppedInDepot(v)) { GSVehicle.SellVehicle(v); return; }
    while (GSOrder.GetOrderCount(v) > 0) { if (!GSOrder.RemoveOrder(v, 0)) break; }
    GSOrder.AppendOrder(v, d, GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local s = 0; s < 40; s++) {
        if (!GSVehicle.IsValidVehicle(v) || GSVehicle.IsStoppedInDepot(v)) break;
        GSController.Sleep(6);
    }
    if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
}
// STAGE 2 deterministic input placement (see xorsum1::ParkInput): the input RESTS inside its gate's
// protected block [sigx..sigtx] by construction, confirmed before the reader runs; confirm-and
// -rebuild on a stuck egress or an overshoot. The feeder depot d sits at (dx,dy)=(tx,gy-1).
function FaComboMain::ParkInput(d, tx, gy, dx, dy, sigx, sigtx) {
    for (local attempt = 0; attempt < 4; attempt++) {
        local v = null;
        for (local b = 0; b < 20; b++) {
            v = GSVehicle.BuildVehicle(d, this.eng);
            if (GSVehicle.IsValidVehicle(v)) break;
            GSController.Sleep(6);
        }
        if (!GSVehicle.IsValidVehicle(v)) { GSController.Sleep(8); continue; }
        GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (!this.NudgeEgress(v, dx, dy)) { this.Scrap(v, d); continue; }
        local parked = false;
        for (local w = 0; w < 60; w++) {
            GSController.Sleep(3);
            if (!GSVehicle.IsValidVehicle(v)) break;
            local cx = this.Tx(v); local cy = this.Ty(v);
            if (cy == gy && cx >= tx && cx <= sigtx) { GSVehicle.StartStopVehicle(v); parked = true; break; }
            if (cy == gy && cx > sigtx) break;
        }
        if (!parked) { this.Scrap(v, d); continue; }
        for (local s = 0; s < 16; s++) {
            GSController.Sleep(4);
            if (!GSVehicle.IsValidVehicle(v)) break;
            if (GSVehicle.GetCurrentSpeed(v) == 0) break;
        }
        if (GSVehicle.IsValidVehicle(v)) {
            local cx = this.Tx(v); local cy = this.Ty(v);
            if (cy == gy && cx >= sigx && cx <= sigtx) return v;
        }
        this.Scrap(v, d);
    }
    return null;
}
// OCCUPANCY-GUARDED park: park an input ONLY if its gate row (gy) is not already occupied by a sibling
// input. A block-signal NOR is held iff ANY input is present in [sigx..sigtx], so once the first input
// of a multi-input gate is parked the block is occupied and the gate's value is final; a second input
// on the SAME row is logically redundant AND physically unparkable (the occupied block's red signal
// stops it at the depot exit, so ParkInput would burn its full retry budget and return null). This is
// the combo-111 fix: skip the redundant second park (a fast no-op) instead of stalling ~88s on it. The
// LOGIC is identical (the NOR still reads the block as occupied); the output is still raw reader x.
function FaComboMain::ParkOcc(d, tx, gy, dx, dy, sigx, sigtx) {
    if (gy in this.occRows) return this.occRows[gy];   // already occupied by a sibling: redundant, skip
    local v = this.ParkInput(d, tx, gy, dx, dy, sigx, sigtx);
    if (v != null) this.occRows[gy] <- v;              // record the row as occupied for this combo
    return v;
}
// Build a reader and CONFIRM it left its west depot (STAGE 1 egress hardening). (dx,dy) is the west
// depot tile; scrap-and-rebuild on a stuck egress. Fixes the raw x = -1 misses (stuck readers).
function FaComboMain::BuildReader(wd, ed, dx, dy) {
    if (!GSRail.IsRailDepotTile(wd))
        for (local d = 0; d < 10 && !GSRail.IsRailDepotTile(wd); d++) GSController.Sleep(5);
    for (local attempt = 0; attempt < 4; attempt++) {
        local v = null;
        for (local b = 0; b < 40; b++) {
            v = GSVehicle.BuildVehicle(wd, this.eng);
            if (GSVehicle.IsValidVehicle(v)) break;
            GSController.Sleep(8);
        }
        if (!GSVehicle.IsValidVehicle(v)) { GSController.Sleep(8); continue; }
        GSOrder.AppendOrder(v, ed, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (this.NudgeEgress(v, dx, dy)) return v;
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        GSController.Sleep(8);
    }
    return null;
}
function FaComboMain::RunFreeze(wd, ed, gy, sigx, cpl) {
    local v = this.BuildReader(wd, ed, GSMap.GetTileX(wd), GSMap.GetTileY(wd));
    if (v == null) return -1;
    local fx = -1;
    for (local s = 0; s < 200; s++) {
        GSController.Sleep(3);
        fx = this.Tx(v);
        local ty = this.Ty(v);
        if (fx < 0) continue;
        local diverted = (fx > sigx && ty != gy);
        if (fx >= cpl || diverted) { GSVehicle.StartStopVehicle(v); fx = this.Tx(v); break; }
        if (fx > sigx && fx < cpl && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    }
    return fx;
}
// Patient far-freeze (for the cout r3 root whose coupling column is east of an intervening lane).
function FaComboMain::RunFreezeFar(wd, ed, gy, sigx, cpl) {
    local v = this.BuildReader(wd, ed, GSMap.GetTileX(wd), GSMap.GetTileY(wd));
    if (v == null) return -1;
    local fx = -1;
    for (local s = 0; s < 420; s++) {
        GSController.Sleep(3);
        if (!GSVehicle.IsValidVehicle(v)) break;
        fx = this.Tx(v);
        local ty = this.Ty(v);
        if (fx < 0) continue;
        local diverted = (fx > sigx && ty != gy);
        if (fx >= cpl || diverted) { GSVehicle.StartStopVehicle(v); fx = this.Tx(v); break; }
        if (fx > sigx && fx < cpl) { if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v); }
    }
    return fx;
}
// Run a final output reader; record where it rests. Returns final raw x. RETRY-ON-MISS: a final
// output reader that returns -1 is a pure dispatch miss (BuildReader's egress failed all its attempts,
// or the freshly built reader never moved) - the documented residual dispatch-miss axis, which on the
// heavy combo 111 showed as the CARRY gm reader intermittently not launching (FC40 -1) even though the
// SUM read cleanly. A -1 carries no logic information, so we scrap the stuck reader and rebuild the
// whole read up to a few times; the first attempt that yields a real position wins. This costs nothing
// on the common case (a reader that launches returns on attempt 1) and removes the -1 misses. The
// output is still ONLY the raw reader x; nothing is computed in Squirrel.
function FaComboMain::RunReader(wd, ed) {
    for (local attempt = 0; attempt < 4; attempt++) {
        local v = this.BuildReader(wd, ed, GSMap.GetTileX(wd), GSMap.GetTileY(wd));
        if (v == null) { GSController.Sleep(10); continue; }
        local fx = -1;
        for (local s = 0; s < 24; s++) { GSController.Sleep(12); local t = this.Tx(v); if (t >= 0) fx = t; }
        if (fx >= 0) return fx;
        // never moved (stuck reader): scrap it and rebuild so it does not foul the lane, then retry.
        this.Scrap(v, wd);
        GSController.Sleep(8);
    }
    return -1;
}

// THE RECONVERGENT FREEZE (deterministic coupling-tile landing), PORTED VERBATIM from xorsum1 (PROVEN
// ~92% logic-clean). A reconvergent DRIVER whose frozen reader must occupy the consumer's input block
// THROUGH a BRIDGED spur (g3->g4 over column C_CPL, NHb->Q over column NHb_CPL) cannot use the plain
// RunFreeze: an ASYNC StartStop fired at fx>=cpl lets the train DRIFT, and on a narrow coupling block
// the drift can carry it PAST the block into a region DISCONNECTED from the spur, so the consumer reads
// empty and wrongly passes (the c00-style flake). Two changes fix it deterministically:
//   (i) the coupling block is WIDE ([cpl..term2], geometry widened above), so any rest there occupies
//       the spur; and
//   (ii) this freeze CONFIRMS the landing: a PASSING driver is pinned at/past cpl and strictly WEST of
//        term2 (or diverted off-row into the spur); a genuinely HELD driver rests at sigx-1 and is
//        returned as-is. The EGRESS-UNDERSHOOT STALL (a reader stalled mid-lane WEST of its held
//        position, never reaching the coupling block, indistinguishable from a held output-0) is
//        detected and the reader is SCRAPPED + rebuilt (the ParkInput rebuild-on-stuck model).
function FaComboMain::RunG3Freeze(wd, ed, gy, sigx, sigtx, cpl, term2) {
    local fx = -1;
    for (local attempt = 0; attempt < 4; attempt++) {
        local v = this.BuildReader(wd, ed, GSMap.GetTileX(wd), GSMap.GetTileY(wd));
        if (v == null) { GSController.Sleep(8); continue; }
        local res = this.RunG3FreezeOnce(v, gy, sigx, sigtx, cpl, term2);
        fx = res.fx;
        if (res.stalled) { this.Scrap(v, wd); GSController.Sleep(8); continue; }
        return fx;
    }
    return fx;
}
// One reconvergent freeze attempt on an already-dispatched reader v. Returns { fx, stalled }.
// stalled == true means the reader rests ON-ROW STRICTLY WEST of its held position (cx<sigx-1) and is
// not advancing: an egress-undershoot stall, NOT a genuine held output-0, so the caller rebuilds.
function FaComboMain::RunG3FreezeOnce(v, gy, sigx, sigtx, cpl, term2) {
    local fx = -1;
    for (local s = 0; s < 200; s++) {
        GSController.Sleep(3);
        fx = this.Tx(v);
        local ty = this.Ty(v);
        if (fx < 0) continue;
        local diverted = (fx > sigx && ty != gy);
        if ((fx >= cpl) || diverted) { GSVehicle.StartStopVehicle(v); break; }
        if (fx > sigx && fx < cpl && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    }
    // PIN-AND-VERIFY: drive a passing driver to rest strictly inside the coupling block [cpl..term2-1]
    // so its occupancy is on the spur; a held driver rests at sigx-1.
    for (local p = 0; p < 24; p++) {
        if (!GSVehicle.IsValidVehicle(v)) break;
        local cx = this.Tx(v); local cy = this.Ty(v);
        if (cx < 0) { GSController.Sleep(4); continue; }
        local offrow = (cy != gy);
        local held = (cx == sigx - 1 && cy == gy);
        if (held) break;
        if (offrow) break;
        if (cx >= cpl && cx < term2) break;
        if (cx < cpl) {
            if (GSVehicle.GetCurrentSpeed(v) == 0) GSVehicle.StartStopVehicle(v);
            GSController.Sleep(4);
            if (GSVehicle.IsValidVehicle(v) && this.Tx(v) >= cpl) GSVehicle.StartStopVehicle(v);
        }
        GSController.Sleep(4);
    }
    for (local s = 0; s < 12; s++) {
        GSController.Sleep(4);
        if (!GSVehicle.IsValidVehicle(v) || GSVehicle.GetCurrentSpeed(v) == 0) break;
    }
    fx = this.Tx(v);
    local cy = this.Ty(v);
    local stalled = (fx >= 0 && cy == gy && fx < sigx - 1);
    return { fx = fx, stalled = stalled };
}

// Build ONE independent FULL-ADDER copy at combo base row gy: the SUM network (rows gy+0..gy+43)
// and the CARRY network (rows gy+COUT+0..gy+COUT+9), each fully independent. VERBATIM from fulladder_gs.
function FaComboMain::BuildCopy(gy) {
    // ---- SUM : XOR1 (produces h) ----
    local ya = gy+DY_A, yb = gy+DY_B, yc = gy+DY_C, yd = gy+DY_D, ye = gy+DY_E, yf = gy+DY_F;
    local la = this.BuildLane(A_BX, A_EAST, ya, A_SIG, A_SIGT, 0);
    local lb = this.BuildLane(B_BX, B_EAST, yb, B_SIG, B_SIGT, 0);
    local lc = this.BuildLane(C_BX, C_EAST, yc, C_SIG, C_SIGT, C_TERM2);
    local ld = this.BuildLane(D_BX, D_EAST, yd, D_SIG, D_SIGT, D_TERM2);
    local le = this.BuildLane(E_BX, E_EAST, ye, E_SIG, E_SIGT, E_TERM2);
    local lf = this.BuildLane(F_BX, F_EAST, yf, F_SIG, F_SIGT, 0);
    local fa = { aa = this.FeederDepot(A_TA, ya), ab = this.FeederDepot(A_TB, ya),
                 ea = this.FeederDepot(E_TA, ye), eb = this.FeederDepot(E_TB, ye),
                 b1a = this.FeederDepot(B_TA, yb), d2b = this.FeederDepot(D_TB, yd) };
    this.BuildSpur(A_CPL, ya, yb);
    this.BuildSpur(E_CPL, ye, yd);
    this.BuildSpur(B_CPL, yb, yc);
    this.BuildSpur(D_CPL, yd, yc);
    local br1 = this.BuildBridgedSpur(C_CPL, yc, yf, [yd, ye]);
    if (!br1) this.allbr = false;

    // ---- SUM : XOR2 (consumes h, cin) ----
    local ynha = gy+DY_NHa, ynhb = gy+DY_NHb, yhh = gy+DY_HH, yp = gy+DY_P, yy = gy+DY_Y, yq = gy+DY_Q, ync = gy+DY_NC;
    local lnha = this.BuildLane(NHa_BX, NHa_EAST, ynha, NHa_SIG, NHa_SIGT, 0);
    local lnhb = this.BuildLane(NHb_BX, NHb_EAST, ynhb, NHb_SIG, NHb_SIGT, NHb_TERM2);
    local lhh = this.BuildLane(HH_BX, HH_EAST, yhh, HH_SIG, HH_SIGT, 0);
    local lp  = this.BuildLane(P_BX,  P_EAST,  yp,  P_SIG,  P_SIGT, 0);
    local lyy = this.BuildLane(Y_BX,  Y_EAST,  yy,  Y_SIG,  Y_SIGT, 0);
    local lq  = this.BuildLane(Q_BX,  Q_EAST,  yq,  Q_SIG,  Q_SIGT, Q_TERM2);
    local lnc = this.BuildLane(NC_BX, NC_EAST, ync, NC_SIG, NC_SIGT, 0);
    local fc = { nc = this.FeederDepot(NC_TCIN, ync), p = this.FeederDepot(P_TCIN, yp) };
    this.BuildSpur(NHa_CPL, ynha, yhh);
    this.BuildSpur(HH_CPL, yhh, yp);
    this.BuildSpur(NC_CPL, ync, yq);
    this.BuildSpur(P_CPL, yp, yy);
    this.BuildSpur(Q_CPL, yq, yy);
    local br2 = this.BuildBridgedSpur(NHb_CPL, ynhb, yq, [ynha, yhh, yp, yy]);
    if (!br2) this.allbr = false;
    local br4 = this.BuildBridgedSpur(F_CPL, yf, ynha, []);
    if (!br4) this.allbr = false;

    // ---- CARRY : majority network (fulladder_cout), rows gy+COUT.. ----
    local y1 = gy+DY_R1, ym = gy+DY_GM, y2 = gy+DY_R2, y3 = gy+DY_R3;
    local l1 = this.BuildLane(R1_BX, R1_EAST, y1, R1_SIG, R1_SIGT, 0);
    local lm = this.BuildLane(GM_BX, GM_EAST, ym, GM_SIG, GM_SIGT, 0);
    local l2 = this.BuildLane(R2_BX, R2_EAST, y2, R2_SIG, R2_SIGT, 0);
    local l3 = this.BuildLane(R3_BX, R3_EAST, y3, R3_SIG, R3_SIGT, R3_TERM2);
    local fm = { r1a = this.FeederDepot(R1_TA, y1), r1b = this.FeederDepot(R1_TB, y1),
                 r2a = this.FeederDepot(R2_TA, y2), r2c = this.FeederDepot(R2_TC, y2),
                 r3b = this.FeederDepot(R3_TB, y3), r3c = this.FeederDepot(R3_TC, y3) };
    this.BuildSpur(R1_CPL, y1, ym);
    this.BuildSpur(R2_CPL, y2, ym);
    this.BuildSpur(R3_CPL, y3, ym);

    return { gy = gy, ya=ya,yb=yb,yc=yc,yd=yd,ye=ye,yf=yf,
             ynha=ynha,ynhb=ynhb,yhh=yhh,yp=yp,yy=yy,yq=yq,ync=ync,
             la=la,lb=lb,lc=lc,ld=ld,le=le,lf=lf, lnha=lnha,lnhb=lnhb,lhh=lhh,lp=lp,lyy=lyy,lq=lq,lnc=lnc,
             fa=fa, fc=fc,
             y1=y1,ym=ym,y2=y2,y3=y3, l1=l1,lm=lm,l2=l2,l3=l3, fm=fm };
}

// Run one combo (a,b,cin): run the SUM network -> s, then the CARRY network -> cout. VERBATIM.
function FaComboMain::RunCase(c, a, b, cin) {
    // SUM primaries. ParkOcc parks deterministically inside the gate's protected block [sig..sigt] but
    // SKIPS a redundant second park on an ALREADY-OCCUPIED gate row (the combo-111 fix): gates g0a (row
    // ya) and g0b (row ye) take BOTH a and b, so on the all-ones case the second input's block is already
    // held by the first, the second train cannot enter, and parking it would burn ParkInput's full ~88s
    // budget for no logic change. A block-signal NOR reads the block as occupied iff ANY input is present.
    this.occRows = {};   // fresh per-combo occupancy (one combo per run, but keep it clean)
    if (a) this.ParkOcc(c.fa.aa, A_TA, c.ya, A_TA, c.ya - 1, A_SIG, A_SIGT);
    if (b) this.ParkOcc(c.fa.ab, A_TB, c.ya, A_TB, c.ya - 1, A_SIG, A_SIGT);
    if (a) this.ParkOcc(c.fa.ea, E_TA, c.ye, E_TA, c.ye - 1, E_SIG, E_SIGT);
    if (b) this.ParkOcc(c.fa.eb, E_TB, c.ye, E_TB, c.ye - 1, E_SIG, E_SIGT);
    if (a) this.ParkOcc(c.fa.b1a, B_TA, c.yb, B_TA, c.yb - 1, B_SIG, B_SIGT);
    if (b) this.ParkOcc(c.fa.d2b, D_TB, c.yd, D_TB, c.yd - 1, D_SIG, D_SIGT);
    if (cin) this.ParkOcc(c.fc.nc, NC_TCIN, c.ync, NC_TCIN, c.ync - 1, NC_SIG, NC_SIGT);
    if (cin) this.ParkOcc(c.fc.p, P_TCIN, c.yp, P_TCIN, c.yp - 1, P_SIG, P_SIGT);
    GSController.Sleep(8);
    // SUM XOR1 -> freeze g4 = h
    this.RunFreeze(c.la.wd, c.la.ed, c.ya, A_SIG, A_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.le.wd, c.le.ed, c.ye, E_SIG, E_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.lb.wd, c.lb.ed, c.yb, B_SIG, B_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.ld.wd, c.ld.ed, c.yd, D_SIG, D_CPL);  GSController.Sleep(6);
    // g3 is the XOR1 reconvergence (NOR(n2,n3)) whose frozen reader must occupy g4's input THROUGH the
    // bridged g3->g4 spur (column C_CPL=45). Use the PROVEN RunG3Freeze (widened block [45..50] + pin +
    // egress-stall rebuild), not plain RunFreeze, so the coupling delivers reliably (the xorsum1 fix).
    this.RunG3Freeze(c.lc.wd, c.lc.ed, c.yc, C_SIG, C_SIGT, C_CPL, C_TERM2);  GSController.Sleep(6);
    local hbit = this.RunFreeze(c.lf.wd, c.lf.ed, c.yf, F_SIG, F_CPL);
    GSController.Sleep(20);
    // SUM XOR2 -> Y = s
    this.RunFreeze(c.lnha.wd, c.lnha.ed, c.ynha, NHa_SIG, NHa_CPL);  GSController.Sleep(6);
    // NHb is the XOR2 reconvergent bridged driver (NOR(h)) whose frozen reader must occupy Q's input
    // THROUGH the bridged NHb->Q spur (column 53). Use RunG3Freeze (widened block [53..56] + pin +
    // egress-stall rebuild), the same proven fix as g3, so the bridged coupling delivers reliably.
    this.RunG3Freeze(c.lnhb.wd, c.lnhb.ed, c.ynhb, NHb_SIG, NHb_SIGT, NHb_CPL, NHb_TERM2);  GSController.Sleep(6);
    this.RunFreeze(c.lhh.wd, c.lhh.ed, c.yhh, HH_SIG, HH_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.lnc.wd, c.lnc.ed, c.ync, NC_SIG, NC_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.lp.wd, c.lp.ed, c.yp, P_SIG, P_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.lq.wd, c.lq.ed, c.yq, Q_SIG, Q_CPL);  GSController.Sleep(40);
    local s = this.RunReader(c.lyy.wd, c.lyy.ed);

    // CARRY primaries. Same ParkOcc occupancy guard: R1 (row y1, a+b), R2 (row y2, a+cin) and R3 (row
    // y3, b+cin) are the majority network's shared two-input gates, all driven on the all-ones combo, so
    // their redundant second parks are skipped exactly like the SUM's g0a/g0b. The CARRY occupancy is
    // tracked alongside the SUM in occRows (every gate is on its own unique row, so the keys never clash).
    if (a)   this.ParkOcc(c.fm.r1a, R1_TA, c.y1, R1_TA, c.y1 - 1, R1_SIG, R1_SIGT);
    if (b)   this.ParkOcc(c.fm.r1b, R1_TB, c.y1, R1_TB, c.y1 - 1, R1_SIG, R1_SIGT);
    if (a)   this.ParkOcc(c.fm.r2a, R2_TA, c.y2, R2_TA, c.y2 - 1, R2_SIG, R2_SIGT);
    if (cin) this.ParkOcc(c.fm.r2c, R2_TC, c.y2, R2_TC, c.y2 - 1, R2_SIG, R2_SIGT);
    if (b)   this.ParkOcc(c.fm.r3b, R3_TB, c.y3, R3_TB, c.y3 - 1, R3_SIG, R3_SIGT);
    if (cin) this.ParkOcc(c.fm.r3c, R3_TC, c.y3, R3_TC, c.y3 - 1, R3_SIG, R3_SIGT);
    GSController.Sleep(8);
    this.RunFreeze(c.l1.wd, c.l1.ed, c.y1, R1_SIG, R1_CPL);  GSController.Sleep(6);
    this.RunFreeze(c.l2.wd, c.l2.ed, c.y2, R2_SIG, R2_CPL);  GSController.Sleep(6);
    this.RunFreezeFar(c.l3.wd, c.l3.ed, c.y3, R3_SIG, R3_CPL);  GSController.Sleep(40);
    local m = this.RunReader(c.lm.wd, c.lm.ed);

    return { h = hbit, s = s, m = m };
}

function FaComboMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());

    // SELECT the combo. Primary channel: the runner-rewritten COMBO_SEL source constant (reliable on a
    // dedicated-server newgame, where the GS setting is not applied). If a future build DOES deliver the
    // GS setting, a non-zero setting overrides (so both channels work); otherwise COMBO_SEL governs.
    local sel = COMBO_SEL;
    local setv = GSController.GetSetting("combo");
    if (setv > 0) sel = setv;
    if (sel < 0) sel = 0; if (sel > 7) sel = 7;
    local a = (sel >> 2) & 1;
    local b = (sel >> 1) & 1;
    local cin = sel & 1;

    this.Say("FA build c" + a + b + cin);
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    // WORLD-READY SETTLE (the clockgate fix): on a freshly launched dedicated server the first build
    // commands can fire before the economy/map are ready. Wait for a valid buildable engine, settle.
    for (local w = 0; w < 40 && this.eng == null; w++) { GSController.Sleep(10); this.eng = this.PickEngine(rt); }
    GSController.Sleep(20);

    // ONE combo band only (BASE..BASE+DY_R3), so a small bounded rectangle. Chunked Prepare kept.
    local lastY = BASE + DY_R3;
    this.Prepare(A_BX - 2, BASE - 2, Y_EAST + 2, lastY + 2, "FA");

    local copy = this.BuildCopy(BASE);
    this.Say("FA built1 b" + (this.allbr ? 1 : 0));
    GSController.Sleep(4);

    local s = -1, m = -1;
    try {
        local r = this.RunCase(copy, a, b, cin);
        s = r.s; m = r.m;
        this.Say("c" + a + b + cin + " s" + s + " m" + m);
    } catch (e) {
        this.Say("c" + a + b + cin + " ERR");
    }
    GSController.Sleep(8);

    // Latched short readouts streamed in turn (each under the ~31-char name limit). The combo digits
    // are in the per-combo line above; here we expose the raw x next to the thresholds.
    // SUM:  x > Y_SIG(50) => sum 1.   COUT: x > GM_SIG(40) => cout 1.
    local ns = "FA" + Y_SIG + " " + s + " c" + a + b + cin;
    local nm = "FC" + GM_SIG + " " + m + " c" + a + b + cin;
    while (true) { this.Say(ns); GSController.Sleep(60); this.Say(nm); GSController.Sleep(60); }
}

function FaComboMain::Save() { return {}; }
function FaComboMain::Load(version, data) {}
