/*
 * xorsum1: STAGE 1, the half-adder SUM bit (a XOR b) as the SAME 6-gate NOR network as stageB,
 * but with the reconvergent output coupling (g3 -> g4) routed as a BRIDGE instead of the flaky
 * far-push east. This is the reliability fix the brief asks for: stageB pushed g3's coupling tile
 * far east (column 50, filler track) to clear the two intervening lanes (g2, g0b), which put g3's
 * freeze tile in a long merged block that only settled ~57% of the time. Here g3's coupling tile
 * sits CLOSE (right past its terminating signal), and the vertical g3 -> g4 spur BRIDGES over the
 * g2 and g0b lanes it crosses (the bridgeprobe / xorbridge primitive). No far-push, no flaky
 * merged block, the crossings are isolated bridges.
 *
 * NETWORK (identical to stageB, merge-free, the fan-out driver NOR(a,b) duplicated as g0a, g0b):
 *     g0a = NOR(a, b)  -> n1a       g0b = NOR(a, b)  -> n1b
 *     g1  = NOR(a, n1a) -> n2       g2  = NOR(b, n1b) -> n3
 *     g3  = NOR(n2, n3) -> n4       g4  = NOR(n4)     -> y
 * Expected y over (a,b) = 00,01,10,11: 0,1,1,0 = XOR, judged from RAW g4 reader x (x > F_SIG == 1).
 *
 * ROW LAYOUT within a combo band (DY): g0a=0, g1=3, g3=6, g2=9, g0b=12, g4=15. g3 sits BETWEEN
 * its two drivers (g1 above spur DOWN, g2 below spur UP), both short adjacent couplings, exactly
 * stageB. The ONLY change: g3 -> g4 is a single-column vertical spur from g3's row (6) DOWN to
 * g4's row (15), crossing g2's lane (row 9) and g0b's lane (row 12). Each crossing is a length-3
 * N-S BRIDGE over the lane tile (the proven recipe: ramps empty of rail, under-tile carries the
 * E-W lane rail, verify-under-rail + retry). The bridge column COL is chosen to lie strictly
 * inside BOTH crossed lanes' protected blocks (D_SIG < COL < D_SIGT and E_SIG < COL < E_SIGT) so a
 * LEVEL crossing there would visibly short (the bridge's job), and the spur clears g3's terminating
 * signal first (COL > C_SIGT) so g3 freezes on its near CPL before the drop.
 *
 * GEOMETRY reused VERBATIM from stageB / fulladder_cout (all PROVEN): a bit is train-presence on a
 * protected through-block; an eastbound reader passes a normal block signal iff its input block is
 * empty (== NOR of present inputs); BuildSignal(tile, front) permits travel FROM front INTO tile so
 * an eastbound reader needs front = SIG-1; a passing driver reader is FROZEN the instant it clears
 * its terminating signal, on its coupling tile CPL; a short signal-free spur joins CPL into the
 * consumer's input block. Every gate on its own lane, built ONCE per combo (4 SEPARATE copies, no
 * teardown), readers run in topological order, NO per-gate train re-parked between reads. Outputs
 * from RAW reader x only, no XOR in Squirrel.
 *
 * Readout (short): "XS1 s<F_SIG> <y00> <y01> <y10> <y11> b<all bridges built 0/1>".
 */

// ---- absolute column geometry per gate (rows = combo BASE + per-gate DY) ----
// Validated collision-free: each driver's CPL (freeze col, = SIGT+1) equals the consumer's
// coupling-tap column; every tap lies strictly inside its own gate's input block (SIG,SIGT); the
// g3->g4 bridge column C_CPL=45 lies inside BOTH crossed lanes' THROUGH blocks [CPL..TERM2] so a
// level crossing there would short (the bridge is load-bearing); no foreign lane crossings except
// the two intended g3->g4 bridges.
// g0a (root NOR(a,b) -> n1a, spur DOWN to g1)
A_BX <- 30; A_SIG <- 36; A_TA <- 37; A_TB <- 38; A_SIGT <- 39; A_CPL <- 40; A_EAST <- 48;
// g1 (NOR(a,n1a) -> n2, spur DOWN to g3). n1a coupling tap = A_CPL = 40.
B_BX <- 32; B_SIG <- 38; B_TA <- 39; B_TN <- 40; B_SIGT <- 41; B_CPL <- 42; B_EAST <- 50;
// g3 (the reconvergence NOR(n2,n3) -> n4). n2 tap = B_CPL = 42, n3 tap = D_CPL = 43. Its coupling
// tile C_CPL=45 sits CLOSE, just past its terminating signal C_SIGT=44; the vertical g3->g4 spur
// drops in column C_CPL. C_TERM2 east of C_CPL makes the freeze block a proper THROUGH block.
C_BX <- 35; C_SIG <- 41; C_T2 <- 42; C_T3 <- 43; C_SIGT <- 44; C_CPL <- 45; C_TERM2 <- 46; C_EAST <- 52;
// g2 (NOR(b,n1b) -> n3, spur UP to g3). b@40, n1b coupling tap = E_CPL = 41. Couples to g3 at
// D_CPL=43 (inside g3's block). D_TERM2=47 east of the bridge col 45 makes [D_CPL..D_TERM2]=[43..47]
// a g2 THROUGH block CONTAINING the bridge column 45 (so the bridge over g2's lane is load-bearing).
D_BX <- 37; D_SIG <- 38; D_TB <- 40; D_TN <- 41; D_SIGT <- 42; D_CPL <- 43; D_TERM2 <- 47; D_EAST <- 54;
// g0b (root NOR(a,b) -> n1b, spur UP to g2). a@38, b@39. Couples to g2 at E_CPL=41 (inside g2's
// block). E_TERM2=47 east of the bridge col 45 makes [E_CPL..E_TERM2]=[41..47] a g0b THROUGH block
// CONTAINING the bridge column 45 (so the bridge over g0b's lane is load-bearing).
E_BX <- 36; E_SIG <- 37; E_TA <- 38; E_TB <- 39; E_SIGT <- 40; E_CPL <- 41; E_TERM2 <- 47; E_EAST <- 54;
// g4 (NOR(n4) -> y, the output; reads the g3->g4 coupling that arrives in column C_CPL=45).
F_BX <- 42; F_SIG <- 44; F_TN <- 45; F_SIGT <- 49; F_CPL <- 50; F_EAST <- 56;

// per-gate row offsets within a combo band. g2 (DY_D=9) and g0b (DY_E=13) are 4 rows apart so the
// two g3->g4 bridges (spans 8-10 and 12-14) are separated by plain spur track at row 11.
DY_A <- 0; DY_B <- 3; DY_C <- 6; DY_D <- 9; DY_E <- 13; DY_F <- 16;

BASE <- 30;   // first combo's g0a lane row
BAND <- 24;   // rows between successive combo bands (17 span + slack)

class XorSum1Main extends GSController {
    company = null; eng = null; allbr = true;
    constructor() {}
}

function XorSum1Main::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function XorSum1Main::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function XorSum1Main::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function XorSum1Main::Say(s) { GSCompany.SetName(s); }
function XorSum1Main::Prepare(x0, y0, x1, y1) {
    // YIELD inside the demolish loop: a tight ~3000-tile DemolishTile loop with no Sleep floods the
    // command queue / opcode budget in one GS step, which OpenTTD handles by RELOADING the script
    // (the readout resets to "XS1 build" mid-run). Sleeping every row drains the queue and keeps the
    // GS alive, the same fix STATUS.md notes for SC2's ~1000-tile Prepare.
    for (local x = x0; x <= x1; x++) {
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
        GSController.Sleep(1);
    }
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSController.Sleep(2);
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Build a NORMAL signal at (sx,gy) facing east (front sx-1), VERIFIED with confirm-and-retry.
function XorSum1Main::SignalVerified(sx, gy) {
    local t = GSMap.GetTileIndex(sx, gy);
    local f = GSMap.GetTileIndex(sx - 1, gy);
    for (local i = 0; i < 8; i++) {
        if (GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE) return true;
        GSRail.BuildSignal(t, f, GSRail.SIGNALTYPE_NORMAL);
        GSController.Sleep(2);
    }
    return GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE;
}

// Build a horizontal gate lane (track + 2 depots + reader signal + terminating signal). term2x>0
// adds a third terminating signal east of the freeze tile so a far freeze block is a THROUGH block.
function XorSum1Main::BuildLane(bx, eastx, gy, sigx, sigtx, term2x) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
    GSController.Sleep(1);   // yield to drain the build command queue (keeps the GS from being reloaded)
    local wd = GSMap.GetTileIndex(bx - 1, gy);
    GSRail.BuildRailDepot(wd, GSMap.GetTileIndex(bx, gy));
    local ed = GSMap.GetTileIndex(eastx, gy);
    GSRail.BuildRailDepot(ed, GSMap.GetTileIndex(eastx - 1, gy));
    this.SignalVerified(sigx, gy);
    this.SignalVerified(sigtx, gy);
    if (term2x > 0) this.SignalVerified(term2x, gy);
    return { wd = wd, ed = ed };
}

// A feeder depot just NORTH of tap tile (tx,gy), joined into the lane.
function XorSum1Main::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// A pure-vertical signal-free coupling spur in column cplx from row gya to row gyb (either order),
// with corner pieces joining each end lane (exactly norchain / stageB's spur).
function XorSum1Main::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}

// The g3->g4 coupling spur in column cplx from row gya(top, g3) to row gyb(bottom, g4), crossing
// the two intervening lanes at rows ly1 (g2) and ly2 (g0b). Each crossing is a length-3 N-S BRIDGE
// over the lane tile (the proven bridgeprobe / xorbridge recipe). Returns true iff BOTH bridges
// built. The spur rail is laid on every row EXCEPT the bridge spans (ly-1, ly, ly+1) of each
// crossing; the bridge ramps must be empty of rail; the under-tile carries the E-W lane rail.
function XorSum1Main::BuildBridgedSpur(cplx, gya, gyb, ly1, ly2) {
    // vertical spur rail on all rows except the two bridge spans.
    for (local y = gya; y <= gyb; y++) {
        if (y >= ly1 - 1 && y <= ly1 + 1) continue;
        if (y >= ly2 - 1 && y <= ly2 + 1) continue;
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    }
    // corner pieces joining the spur ends into the horizontal lanes at top (g3) and bottom (g4).
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, gya), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, gyb), GSRail.RAILTRACK_NW_NE);
    local ok = true;
    ok = this.BuildOneBridge(cplx, ly1) && ok;
    ok = this.BuildOneBridge(cplx, ly2) && ok;
    return ok;
}

// One length-3 N-S bridge in column cplx over lane row ly. Ensures the under-tile carries the lane
// E-W rail first, then builds the bridge (head=ly-1, tail=ly+1), verify-and-retry.
function XorSum1Main::BuildOneBridge(cplx, ly) {
    for (local i = 0; i < 8 && !GSRail.IsRailTile(GSMap.GetTileIndex(cplx, ly)); i++) {
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, ly), GSRail.RAILTRACK_NE_SW);
        GSController.Sleep(3);
    }
    local head = GSMap.GetTileIndex(cplx, ly - 1);
    local tail = GSMap.GetTileIndex(cplx, ly + 1);
    local len = GSMap.DistanceManhattan(head, tail) + 1;
    for (local i = 0; i < 12; i++) {
        if (GSBridge.IsBridgeTile(head)) break;
        local types = GSBridgeList_Length(len);
        if (!types.IsEmpty()) GSBridge.BuildBridge(GSVehicle.VT_RAIL, types.Begin(), head, tail);
        GSController.Sleep(4);
    }
    return GSBridge.IsBridgeTile(head);
}

// ---- SHARED EGRESS HARDENING (the proven main_clocked.nut NudgeEgress pattern) ----
//
// THE DIAGNOSED FLAW (reused from the clock launch). Egress used a tight poll
//     if (IsStoppedInDepot) StartStopVehicle; Sleep(small); if (!IsStoppedInDepot) break;
// StartStopVehicle TOGGLES the stopped flag and is an ASYNCHRONOUS (queued) command: after it
// fires the train stays IsStoppedInDepot==true for several ticks until the command lands and the
// train physically clears the depot tile. A tight re-poll re-reads true and fires a SECOND toggle,
// which RE-STOPS the train once both land. Under server load this oscillates and ~1 in 3 fresh
// dispatches the train never leaves the depot inside the budget (the raw x = -1 miss for readers,
// the wrongly-absent input for inputs). FIX: fire EXACTLY ONE start toggle per SETTLE, and verify
// movement (the train tile is no longer the depot tile) before declaring egress.
//
// One-shot, settle-verified depot egress for a vehicle whose depot tile is (dx,dy). Fires at most
// one start toggle per settle; returns true once the train has left the depot tile.
function XorSum1Main::NudgeEgress(v, dx, dy) {
    for (local r = 0; r < 40; r++) {
        if (!GSVehicle.IsValidVehicle(v)) return false;
        local cx = this.Tx(v); local cy = this.Ty(v);
        if (cx >= 0 && !(cx == dx && cy == dy) && !GSVehicle.IsStoppedInDepot(v)) return true;
        // fire a fresh toggle ONLY when CONFIRMED still stopped in the depot (a dropped command);
        // a started-but-not-yet-moving train is left alone so a command in flight is never doubled.
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(10);
    }
    return (GSVehicle.IsValidVehicle(v) && !GSVehicle.IsStoppedInDepot(v));
}

// STAGE 2 (DETERMINISTIC INPUT PLACEMENT): park an input train so it RESTS inside the gate's
// protected input block [sigx..sigtx] BY CONSTRUCTION, confirmed before the reader runs, instead
// of catching a moving train on a single tap tile (the SC2/fasum flake: a train that crosses the
// tap between polls overshoots to the east depot and the input reads wrongly ABSENT).
//
// MECHANISM. The input drops from feeder depot d (north of the tap) onto tap tile (tx,gy) heading
// EAST, ordered to the tap. With reliable egress it leaves the depot; then we WATCH its position
// and FREEZE it (one StartStop) the first poll its x is at or past the tap and still inside the
// protected block [sigx..sigtx]. The freeze leaves it occupying the input block, which is all the
// NOR read needs (presence anywhere in [sigx..sigtx], not the exact tap tile). CONFIRM-AND-REBUILD:
// if it never left the depot, or overshot past sigtx (the east depot), we tear it down and rebuild,
// up to a budget. Returns the train (parked, confirmed in-block) or null on exhaustion.
function XorSum1Main::ParkInput(d, tx, gy, dx, dy, sigx, sigtx) {
    for (local attempt = 0; attempt < 4; attempt++) {
        local v = null;
        for (local b = 0; b < 20; b++) {
            v = GSVehicle.BuildVehicle(d, this.eng);
            if (GSVehicle.IsValidVehicle(v)) break;
            GSController.Sleep(6);
        }
        if (!GSVehicle.IsValidVehicle(v)) { GSController.Sleep(8); continue; }
        GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
        // reliable egress: leave the feeder depot deterministically (no double-toggle).
        if (!this.NudgeEgress(v, dx, dy)) { this.Scrap(v, d); continue; }
        // watch the train roll east along the lane; FREEZE the first poll it is inside the
        // protected block at or past the tap. A fixed, dense watch so the single-tile tap is not
        // skipped: we accept any x in [tx..sigtx] (the whole input block east of the tap).
        local parked = false;
        for (local w = 0; w < 60; w++) {
            GSController.Sleep(3);
            if (!GSVehicle.IsValidVehicle(v)) break;
            local cx = this.Tx(v); local cy = this.Ty(v);
            if (cy == gy && cx >= tx && cx <= sigtx) { GSVehicle.StartStopVehicle(v); parked = true; break; }
            if (cy == gy && cx > sigtx) break;   // overshot past the block -> rebuild
        }
        if (!parked) { this.Scrap(v, d); continue; }
        // CONFIRM it came to rest inside the block (the freeze toggle is async; give it a beat,
        // then verify it is stationary in [sigx..sigtx]). If it drifted out, rebuild.
        for (local s = 0; s < 16; s++) {
            GSController.Sleep(4);
            if (!GSVehicle.IsValidVehicle(v)) break;
            if (GSVehicle.GetCurrentSpeed(v) == 0) break;
        }
        if (GSVehicle.IsValidVehicle(v)) {
            local cx = this.Tx(v); local cy = this.Ty(v);
            if (cy == gy && cx >= sigx && cx <= sigtx) return v;   // confirmed resting in-block
        }
        this.Scrap(v, d);
    }
    return null;
}

// Dispose a stray input/reader: send it home to depot d if it is on track, then sell it. Guarded so
// a mid-track sell (which fails) never leaks the train; if it will not reach a depot we leave it
// stopped where it is (a wrongly-built input is rare and the rebuild loop replaces it).
function XorSum1Main::Scrap(v, d) {
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

// Build a reader vehicle and CONFIRM it has left its west depot (STAGE 1 egress hardening).
// RETRYING BuildVehicle aggressively until valid, then driving egress with the one-toggle-per
// -settle NudgeEgress (no double-toggle). The west depot tile is (bx-1, gy); a reader that leaves
// it deterministically is the fix for the raw x = -1 misses (a reader that never left its depot).
// On a stuck egress the reader is scrapped and rebuilt, up to a budget. Returns a moving reader or
// null. wd is the west depot tile; (dx,dy) its coordinates; the reader is ordered to ed.
function XorSum1Main::BuildReader(wd, ed, dx, dy) {
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
        if (this.NudgeEgress(v, dx, dy)) return v;   // CONFIRMED out of the depot, moving east
        // stuck in the depot: scrap and rebuild (a leftover stopped reader would jam the lane).
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
        GSController.Sleep(8);
    }
    return null;
}

// Run a gate reader; freeze the instant it clears the terminating signal (x>=cpl) OR it left the
// row after passing the reader signal (started down the spur). A HELD reader rests at sigx-1.
// EXACT stageB-proven structure (no extra hardening) so it does not introduce the GS-restart flake.
function XorSum1Main::RunFreeze(wd, ed, gy, sigx, cpl) {
    // BuildReader now CONFIRMS egress (NudgeEgress), so the old in-function double-toggle poll is
    // gone: a reader returned here has already left its depot (no raw x = -1 from a stuck reader).
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
        // a reader that re-stopped on the lane (rare) gets a single nudge per poll to keep moving.
        if (fx > sigx && fx < cpl && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    }
    return fx;
}

// Run the final gate reader (no freeze); record where it rests. Returns final x. Egress confirmed
// by BuildReader (no double-toggle), so a -1 here means a genuine reader-build failure, not a stuck
// depot egress.
function XorSum1Main::RunReader(wd, ed) {
    local v = this.BuildReader(wd, ed, GSMap.GetTileX(wd), GSMap.GetTileY(wd));
    if (v == null) return -1;
    local fx = -1;
    for (local s = 0; s < 28; s++) { GSController.Sleep(12); local t = this.Tx(v); if (t >= 0) fx = t; }
    return fx;
}

// Build one independent network copy at combo base row gy. Returns a table of run handles.
function XorSum1Main::BuildCopy(gy) {
    local ya = gy + DY_A, yb = gy + DY_B, yc = gy + DY_C, yd = gy + DY_D, ye = gy + DY_E, yf = gy + DY_F;
    local la = this.BuildLane(A_BX, A_EAST, ya, A_SIG, A_SIGT, 0);
    local lb = this.BuildLane(B_BX, B_EAST, yb, B_SIG, B_SIGT, 0);
    local lc = this.BuildLane(C_BX, C_EAST, yc, C_SIG, C_SIGT, C_TERM2);
    // g2 and g0b get a SECOND terminating signal (D_TERM2 / E_TERM2) east of the bridge column 45
    // so the tile the g3->g4 spur bridges over sits inside a defined THROUGH block on each lane.
    local ld = this.BuildLane(D_BX, D_EAST, yd, D_SIG, D_SIGT, D_TERM2);
    local le = this.BuildLane(E_BX, E_EAST, ye, E_SIG, E_SIGT, E_TERM2);
    local lf = this.BuildLane(F_BX, F_EAST, yf, F_SIG, F_SIGT, 0);
    // primary input feeders: g0a a@A_TA b@A_TB ; g0b a@E_TA b@E_TB ; g1 a@B_TA ; g2 b@D_TB.
    local fa = { aa = this.FeederDepot(A_TA, ya), ab = this.FeederDepot(A_TB, ya),
                 ea = this.FeederDepot(E_TA, ye), eb = this.FeederDepot(E_TB, ye),
                 b1a = this.FeederDepot(B_TA, yb), d2b = this.FeederDepot(D_TB, yd) };
    // coupling spurs (driver CPL column, driver row -> consumer row), built UP FRONT:
    this.BuildSpur(A_CPL, ya, yb);   // g0a -> g1  (down)
    this.BuildSpur(E_CPL, ye, yd);   // g0b -> g2  (up)
    this.BuildSpur(B_CPL, yb, yc);   // g1  -> g3  (down)
    this.BuildSpur(D_CPL, yd, yc);   // g2  -> g3  (up)
    // g3 -> g4: the BRIDGED reconvergent output spur (column C_CPL=45), crossing g2 lane (yd) and
    // g0b lane (ye) as two length-3 bridges. This REPLACES stageB's far-push.
    local isBr = this.BuildBridgedSpur(C_CPL, yc, yf, yd, ye);
    if (!isBr) this.allbr = false;
    return { gy = gy, ya = ya, yb = yb, yc = yc, yd = yd, ye = ye, yf = yf,
             la = la, lb = lb, lc = lc, ld = ld, le = le, lf = lf, fa = fa, isBr = isBr };
}

// Run one combo: pre-park primary inputs, then run the six readers in topological order.
// Returns [g0a, g0b, g1, g2, g3, g4] final x.
function XorSum1Main::RunCase(c, a, b) {
    // Each input parks deterministically inside its OWN gate's protected block [sig..sigt]; the
    // feeder depot is one tile NORTH of the tap (tx, gy-1). g0a taps a@A_TA,b@A_TB in [A_SIG..A_SIGT];
    // g0b taps a@E_TA,b@E_TB in [E_SIG..E_SIGT]; g1 taps a@B_TA in [B_SIG..B_SIGT]; g2 taps b@D_TB in
    // [D_SIG..D_SIGT].
    if (a) this.ParkInput(c.fa.aa, A_TA, c.ya, A_TA, c.ya - 1, A_SIG, A_SIGT);
    if (b) this.ParkInput(c.fa.ab, A_TB, c.ya, A_TB, c.ya - 1, A_SIG, A_SIGT);
    if (a) this.ParkInput(c.fa.ea, E_TA, c.ye, E_TA, c.ye - 1, E_SIG, E_SIGT);
    if (b) this.ParkInput(c.fa.eb, E_TB, c.ye, E_TB, c.ye - 1, E_SIG, E_SIGT);
    if (a) this.ParkInput(c.fa.b1a, B_TA, c.yb, B_TA, c.yb - 1, B_SIG, B_SIGT);
    if (b) this.ParkInput(c.fa.d2b, D_TB, c.yd, D_TB, c.yd - 1, D_SIG, D_SIGT);
    GSController.Sleep(8);
    // topological order: g0a, g0b (roots), then g1, g2, then g3, then g4.
    local r0a = this.RunFreeze(c.la.wd, c.la.ed, c.ya, A_SIG, A_CPL);
    GSController.Sleep(6);
    local r0b = this.RunFreeze(c.le.wd, c.le.ed, c.ye, E_SIG, E_CPL);
    GSController.Sleep(6);
    local r1 = this.RunFreeze(c.lb.wd, c.lb.ed, c.yb, B_SIG, B_CPL);
    GSController.Sleep(6);
    local r2 = this.RunFreeze(c.ld.wd, c.ld.ed, c.yd, D_SIG, D_CPL);
    GSController.Sleep(6);
    local r3 = this.RunFreeze(c.lc.wd, c.lc.ed, c.yc, C_SIG, C_CPL);
    GSController.Sleep(40);   // settle: let g3's frozen occupancy settle in g4's block
    local r4 = this.RunReader(c.lf.wd, c.lf.ed);
    return [r0a, r0b, r1, r2, r3, r4];
}

function XorSum1Main::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("XS1 build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastYf = BASE + 3*BAND + DY_F;
    this.Prepare(A_BX - 2, BASE - 2, F_EAST + 2, lastYf + 2);

    local copies = [];
    for (local k = 0; k < 4; k++) { copies.append(this.BuildCopy(BASE + k*BAND)); GSController.Sleep(4); }
    this.Say("XS1 built4 b" + (this.allbr ? 1 : 0));

    local combos = [[0,0],[0,1],[1,0],[1,1]];
    local outs = [-1, -1, -1, -1];
    // Run each combo guarded so an exception cannot crash and restart the GS (an intermittent restart
    // was seen here during c11). Each combo's result is shown as a SHORT per-combo name (the runner
    // records every distinct name, so the per-combo readouts survive in the log even if the final
    // readout is later wiped by a restart), then the FULL readout is latched at the end.
    for (local k = 0; k < 4; k++) {
        try {
            local r = this.RunCase(copies[k], combos[k][0], combos[k][1]);
            outs[k] = r[5];
            this.Say("c" + combos[k][0] + combos[k][1] + " g3" + r[4] + "/g4" + r[5]);
        } catch (e) {
            this.Say("c" + combos[k][0] + combos[k][1] + " ERR");
        }
        GSController.Sleep(4);
    }
    // Encode SHORT: the four g4 (XOR output) final x. Judge: x > F_SIG => output 1. Expected 0,1,1,0.
    local nm = "XS1 s" + F_SIG + " " + outs[0] + " " + outs[1] + " " + outs[2] + " " + outs[3] + " b" + (this.allbr ? 1 : 0);
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function XorSum1Main::Save() { return {}; }
function XorSum1Main::Load(version, data) {}
