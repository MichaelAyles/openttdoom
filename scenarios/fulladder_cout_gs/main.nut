/*
 * fulladder_cout_gs: the FULL-ADDER CARRY-OUT cout = majority(a,b,cin), a fixed NOR network on
 * trains. Verified exhaustively in Python:
 *     cout = NOR3( NOR(a,b), NOR(a,cin), NOR(b,cin) )      (= majority(a,b,cin))
 *
 * NETWORK (3 ROOT NORs of primary taps + 1 terminal 3-input NOR gm):
 *     r1 = NOR(a, b)   -> coupling into gm at tap col T1
 *     r2 = NOR(a, cin) -> coupling into gm at tap col T2
 *     r3 = NOR(b, cin) -> coupling into gm at tap col T3
 *     gm = NOR3(r1, r2, r3) = cout      (gm's protected block straddles T1,T2,T3)
 * cout over (a,b,cin)=000..111: 0,0,0,1,0,1,1,1 = majority, judged from RAW gm reader x.
 *
 * GEOMETRY reused VERBATIM from norchain / stageB / stageBhard (all PROVEN):
 *   - a bit is train-presence on a protected through-block; a reader passes a NORMAL block signal
 *     iff its input block is empty (== NOR of present inputs).
 *   - BuildSignal(tile, front) permits travel FROM front INTO tile, so an eastbound reader needs
 *     front = SIG-1; the input block is terminated by a SECOND signal (a THROUGH block).
 *   - a PASSING root reader is FROZEN the instant it clears its terminating signal, on its
 *     coupling tile CPL; a SHORT signal-free spur joins CPL into gm's input block, merging the
 *     blocks. Root output 1 == a train in gm's input block.
 *   - gm is the TERMINAL output reader (cout), read by where it rests; no freeze, no output spur.
 *
 * gm sits between r1 (above, spur DOWN) and r2 (below, spur UP); r3 is the far-below root whose
 * coupling spur is pushed to a column east of r2's lane (the only crossing). Each gate has its OWN
 * lane; built ONCE per combo (8 SEPARATE copies, no teardown); NO per-gate coupling train re-parked
 * between reads. SignalVerified + settle delays + the patient far-freeze (RunFreezeFar) are the
 * stageBhard hardening, reused.
 *
 * Columns (absolute), rows = combo BASE + per-gate dy:
 *   gate dy  BX  SIG  taps          SIGT CPL  TERM2 EAST   role
 *   r1   0   31  37   [a38,b39]      41   42   0     48     NOR(a,b)   -> gm col 42
 *   gm   3   34  40   [r1@42,r2@43,r3@50] 51 -  0    57     NOR3 = cout (terminal reader)
 *   r2   6   32  38   [a39,c40]      42   43   0     49     NOR(a,cin) -> gm col 43
 *   r3   9   39  45   [b46,c47]      49   50   51    56     NOR(b,cin) -> gm col 50 (far spur up)
 */

R1_BX <- 31; R1_SIG <- 37; R1_TA <- 38; R1_TB <- 39; R1_SIGT <- 41; R1_CPL <- 42; R1_EAST <- 48;
GM_BX <- 34; GM_SIG <- 40; GM_T1 <- 42; GM_T2 <- 43; GM_T3 <- 50; GM_SIGT <- 51; GM_EAST <- 57;
R2_BX <- 32; R2_SIG <- 38; R2_TA <- 39; R2_TC <- 40; R2_SIGT <- 42; R2_CPL <- 43; R2_EAST <- 49;
R3_BX <- 39; R3_SIG <- 45; R3_TB <- 46; R3_TC <- 47; R3_SIGT <- 49; R3_CPL <- 50; R3_TERM2 <- 51; R3_EAST <- 56;

DY_R1 <- 0; DY_GM <- 3; DY_R2 <- 6; DY_R3 <- 9;

BASE <- 30;    // first combo's r1 lane row
BAND <- 16;    // rows between successive combo bands (10 span + slack)

class FullAdderCoutMain extends GSController {
    company = null; eng = null;
    constructor() {}
}

function FullAdderCoutMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function FullAdderCoutMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function FullAdderCoutMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function FullAdderCoutMain::Say(s) { GSCompany.SetName(s); }
function FullAdderCoutMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Build a NORMAL signal at (sx,gy) facing east (front sx-1), VERIFIED with confirm-and-retry.
function FullAdderCoutMain::SignalVerified(sx, gy) {
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
function FullAdderCoutMain::BuildLane(bx, eastx, gy, sigx, sigtx, term2x) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
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
function FullAdderCoutMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// A pure-vertical signal-free coupling spur in column cplx from row gya to row gyb (either order).
function FullAdderCoutMain::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}

// Park an input train on tile (tx,gy) from feeder depot d. Freeze it on the tap. BuildVehicle is
// retried until valid (a failed build would leave that input wrongly absent and corrupt the combo).
function FullAdderCoutMain::ParkInput(d, tx, gy) {
    local v = null;
    for (local b = 0; b < 14; b++) {
        v = GSVehicle.BuildVehicle(d, this.eng);
        if (GSVehicle.IsValidVehicle(v)) break;
        GSController.Sleep(5);
    }
    if (!GSVehicle.IsValidVehicle(v)) return null;
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && GSMap.GetTileX(GSVehicle.GetLocation(v))==tx && GSMap.GetTileY(GSVehicle.GetLocation(v))==gy) { GSVehicle.StartStopVehicle(v); break; }
    }
    return v;
}

// Build a reader vehicle, RETRYING BuildVehicle aggressively until valid. With 8 copies on the map
// the command queue can stay busy for a long stretch, so a short retry budget left some reads as an
// invalid handle (a reader x of -1, seen on gm for some combos). This retries up to 40 times with a
// longer settle, and re-confirms the depot is a valid rail depot first (if the depot itself failed
// to build, no retry helps and we surface that rather than spinning).
function FullAdderCoutMain::BuildReader(wd, ed) {
    if (!GSRail.IsRailDepotTile(wd)) {
        // try to wait for the depot to register (it may still be in the command queue)
        for (local d = 0; d < 10 && !GSRail.IsRailDepotTile(wd); d++) GSController.Sleep(5);
    }
    local v = null;
    for (local b = 0; b < 40; b++) {
        v = GSVehicle.BuildVehicle(wd, this.eng);
        if (GSVehicle.IsValidVehicle(v)) break;
        GSController.Sleep(8);
    }
    if (!GSVehicle.IsValidVehicle(v)) return null;
    GSOrder.AppendOrder(v, ed, GSOrder.OF_NON_STOP_INTERMEDIATE);
    return v;
}

// Run a root reader; freeze the instant it clears the terminating signal (x>=cpl) OR it left the
// row after passing the reader signal (started down the spur). A HELD reader rests at sigx-1.
function FullAdderCoutMain::RunFreeze(wd, ed, gy, sigx, cpl) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 160; s++) {
        GSController.Sleep(3);
        fx = this.Tx(v);
        local ty = this.Ty(v);
        if (fx < 0) continue;
        local diverted = (fx > sigx && ty != gy);
        if (fx >= cpl || diverted) { GSVehicle.StartStopVehicle(v); fx = this.Tx(v); break; }
    }
    return fx;
}

// Patient far-freeze for a root whose coupling tile is east of an intervening lane (r3). Same as
// stageBhard's RunFreezeFar: poll long, never abandon while held short, only re-kick if re-parked.
function FullAdderCoutMain::RunFreezeFar(wd, ed, gy, sigx, sigtx, cpl) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 14; r++) {
        if (!GSVehicle.IsValidVehicle(v)) break;
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
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

// Run the terminal gm reader (cout output); no freeze, record where it rests. Returns final x.
// Uses BuildReader so the BuildVehicle is retried (a busy command queue right after the heavy
// per-copy build can otherwise return an invalid handle, seen as gm = -1).
function FullAdderCoutMain::RunReader(wd, ed) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 24; s++) { GSController.Sleep(12); local t = this.Tx(v); if (t >= 0) fx = t; }
    return fx;
}

// Build one independent COUT network copy at combo base row gy.
function FullAdderCoutMain::BuildCopy(gy) {
    local y1 = gy + DY_R1, ym = gy + DY_GM, y2 = gy + DY_R2, y3 = gy + DY_R3;
    local l1 = this.BuildLane(R1_BX, R1_EAST, y1, R1_SIG, R1_SIGT, 0);
    local lm = this.BuildLane(GM_BX, GM_EAST, ym, GM_SIG, GM_SIGT, 0);
    local l2 = this.BuildLane(R2_BX, R2_EAST, y2, R2_SIG, R2_SIGT, 0);
    local l3 = this.BuildLane(R3_BX, R3_EAST, y3, R3_SIG, R3_SIGT, R3_TERM2);
    // primary feeders: r1 a@R1_TA b@R1_TB ; r2 a@R2_TA c@R2_TC ; r3 b@R3_TB c@R3_TC
    local fd = { r1a = this.FeederDepot(R1_TA, y1), r1b = this.FeederDepot(R1_TB, y1),
                 r2a = this.FeederDepot(R2_TA, y2), r2c = this.FeederDepot(R2_TC, y2),
                 r3b = this.FeederDepot(R3_TB, y3), r3c = this.FeederDepot(R3_TC, y3) };
    // coupling spurs into gm (built UP FRONT so a frozen root immediately occupies gm's input):
    this.BuildSpur(R1_CPL, y1, ym);   // r1 -> gm (down)
    this.BuildSpur(R2_CPL, y2, ym);   // r2 -> gm (up)
    this.BuildSpur(R3_CPL, y3, ym);   // r3 -> gm (up, far col 50 clears r2 lane)
    return { gy = gy, y1 = y1, ym = ym, y2 = y2, y3 = y3, l1 = l1, lm = lm, l2 = l2, l3 = l3, fd = fd };
}

// Run one combo (a,b,c): park primaries, run the 3 roots in order (r1,r2 near; r3 far), read gm.
// Returns [r1x, r2x, r3x, gmx].
function FullAdderCoutMain::RunCase(c, a, b, cin) {
    if (a)   this.ParkInput(c.fd.r1a, R1_TA, c.y1);
    if (b)   this.ParkInput(c.fd.r1b, R1_TB, c.y1);
    if (a)   this.ParkInput(c.fd.r2a, R2_TA, c.y2);
    if (cin) this.ParkInput(c.fd.r2c, R2_TC, c.y2);
    if (b)   this.ParkInput(c.fd.r3b, R3_TB, c.y3);
    if (cin) this.ParkInput(c.fd.r3c, R3_TC, c.y3);
    GSController.Sleep(8);
    local x1 = this.RunFreeze(c.l1.wd, c.l1.ed, c.y1, R1_SIG, R1_CPL);
    GSController.Sleep(6);
    local x2 = this.RunFreeze(c.l2.wd, c.l2.ed, c.y2, R2_SIG, R2_CPL);
    GSController.Sleep(6);
    local x3 = this.RunFreezeFar(c.l3.wd, c.l3.ed, c.y3, R3_SIG, R3_SIGT, R3_CPL);
    GSController.Sleep(40);   // settle: let the three frozen roots' occupancy settle in gm's block
    local xm = this.RunReader(c.lm.wd, c.lm.ed);
    return [x1, x2, x3, xm];
}

function FullAdderCoutMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("FACO build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastY3 = BASE + 7*BAND + DY_R3;
    this.Prepare(R1_BX - 2, BASE - 2, GM_EAST + 1, lastY3 + 2);

    local copies = [];
    for (local k = 0; k < 8; k++) copies.append(this.BuildCopy(BASE + k*BAND));
    this.Say("FACO built8");
    GSController.Sleep(40);

    // 8 combos in order (a,b,cin) = 000,001,010,011,100,101,110,111
    local combos = [[0,0,0],[0,0,1],[0,1,0],[0,1,1],[1,0,0],[1,0,1],[1,1,0],[1,1,1]];
    local outs = [];
    for (local k = 0; k < 8; k++) {
        local r = this.RunCase(copies[k], combos[k][0], combos[k][1], combos[k][2]);
        outs.append(r[3]);
        this.Say("c" + combos[k][0] + combos[k][1] + combos[k][2] + " gm" + r[3]);
    }
    // Encode SHORT (the ~31-char company-name limit): "FC<GM_SIG> <8 gm reader final x>". With
    // GM_SIG=40 and 8 two-digit x this is ~28 chars, safely under the limit. Judge externally:
    // x > GM_SIG => cout 1. (Prefix "FC" not "FACO" to stay short.)
    local nm = "FC" + GM_SIG;
    for (local k = 0; k < 8; k++) nm += " " + outs[k];
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function FullAdderCoutMain::Save() { return {}; }
function FullAdderCoutMain::Load(version, data) {}
