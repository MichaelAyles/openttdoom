/*
 * stageBcarry: the half-adder CARRY bit (a AND b) as a FIXED 3-gate NOR network on trains.
 *     g0 = NOR(a) -> na        (NOT a; root, primary input a)
 *     g1 = NOR(b) -> nb        (NOT b; root, primary input b)
 *     g2 = NOR(na, nb) -> c     (reconvergent fan-in; the output)
 * Carry = AND(a,b). Expected c over (a,b)=00,01,10,11: 0,0,0,1, judged from RAW g2 reader x.
 *
 * GEOMETRY reused VERBATIM from norchain / stageA / stageB (PROVEN): a bit is train-presence
 * on a protected through-block; a reader passes a normal block signal iff its input block is
 * empty (NOR of present inputs). BuildSignal(tile, front) permits travel FROM front INTO tile
 * so an eastbound reader needs front = SIG-1; the input block is terminated by a SECOND signal.
 * A PASSING driver reader is FROZEN the instant it clears its terminating signal, on its
 * coupling tile CPL; a SHORT PURE-VERTICAL signal-free spur joins CPL into the consumer's
 * input block, merging the blocks. The reconvergence g2 = NOR(na,nb) sits BETWEEN its drivers:
 * g0 directly above (spur DOWN), g1 directly below (spur UP), both adjacent. Built ONCE per
 * combo, no per-gate train re-parked between reads; four SEPARATE physical combo copies.
 *
 * Coordinates (rows = combo BASE + dy):
 *   gate dy BX SIG taps      SIGT CPL EAST  role
 *   g0    0 30 36 [37a]      38   39  45    NOT a -> na  (spur DOWN to g2)
 *   g2    3 32 38 [39na,40nb] 41  42  48    NOR(na,nb) -> c (output)
 *   g1    6 31 37 [38b]      39   40  46    NOT b -> nb  (spur UP to g2)
 */

A_BX <- 30; A_SIG <- 36; A_TA <- 37; A_SIGT <- 38; A_CPL <- 39; A_EAST <- 45;   // g0 NOT a
C_BX <- 32; C_SIG <- 38; C_TNA <- 39; C_TNB <- 40; C_SIGT <- 41; C_CPL <- 42; C_EAST <- 48; // g2
B_BX <- 31; B_SIG <- 37; B_TB <- 38; B_SIGT <- 39; B_CPL <- 40; B_EAST <- 46;   // g1 NOT b

DY_A <- 0; DY_C <- 3; DY_B <- 6;
BASE <- 30; BAND <- 12;

class StageBCarryMain extends GSController {
    company = null; eng = null;
    constructor() {}
}

function StageBCarryMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function StageBCarryMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function StageBCarryMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function StageBCarryMain::Say(s) { GSCompany.SetName(s); }
function StageBCarryMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

function StageBCarryMain::BuildLane(bx, eastx, gy, sigx, sigtx) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
    local wd = GSMap.GetTileIndex(bx - 1, gy);
    GSRail.BuildRailDepot(wd, GSMap.GetTileIndex(bx, gy));
    local ed = GSMap.GetTileIndex(eastx, gy);
    GSRail.BuildRailDepot(ed, GSMap.GetTileIndex(eastx - 1, gy));
    GSRail.BuildSignal(GSMap.GetTileIndex(sigx, gy),  GSMap.GetTileIndex(sigx - 1, gy),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(sigtx, gy), GSMap.GetTileIndex(sigtx - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    return { wd = wd, ed = ed };
}
function StageBCarryMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}
function StageBCarryMain::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}
function StageBCarryMain::ParkInput(d, tx, gy) {
    local v = GSVehicle.BuildVehicle(d, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && GSMap.GetTileX(GSVehicle.GetLocation(v))==tx && GSMap.GetTileY(GSVehicle.GetLocation(v))==gy) { GSVehicle.StartStopVehicle(v); break; }
    }
    return v;
}
function StageBCarryMain::RunFreeze(wd, ed, gy, sigx, cpl) {
    local v = GSVehicle.BuildVehicle(wd, this.eng);
    GSOrder.AppendOrder(v, ed, GSOrder.OF_NON_STOP_INTERMEDIATE);
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
function StageBCarryMain::RunReader(wd, ed) {
    local v = GSVehicle.BuildVehicle(wd, this.eng);
    GSOrder.AppendOrder(v, ed, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 24; s++) { GSController.Sleep(12); fx = this.Tx(v); }
    return fx;
}

function StageBCarryMain::BuildCopy(gy) {
    local ya = gy + DY_A, yc = gy + DY_C, yb = gy + DY_B;
    local la = this.BuildLane(A_BX, A_EAST, ya, A_SIG, A_SIGT);
    local lc = this.BuildLane(C_BX, C_EAST, yc, C_SIG, C_SIGT);
    local lb = this.BuildLane(B_BX, B_EAST, yb, B_SIG, B_SIGT);
    local fa = this.FeederDepot(A_TA, ya);   // primary a on g0
    local fb = this.FeederDepot(B_TB, yb);   // primary b on g1
    this.BuildSpur(A_CPL, ya, yc);           // g0 -> g2 (down)
    this.BuildSpur(B_CPL, yb, yc);           // g1 -> g2 (up)
    return { gy = gy, ya = ya, yc = yc, yb = yb, la = la, lc = lc, lb = lb, fa = fa, fb = fb };
}

function StageBCarryMain::RunCase(c, a, b) {
    if (a) this.ParkInput(c.fa, A_TA, c.ya);
    if (b) this.ParkInput(c.fb, B_TB, c.yb);
    GSController.Sleep(8);
    local r0 = this.RunFreeze(c.la.wd, c.la.ed, c.ya, A_SIG, A_CPL);   // g0 NOT a
    GSController.Sleep(6);
    local r1 = this.RunFreeze(c.lb.wd, c.lb.ed, c.yb, B_SIG, B_CPL);   // g1 NOT b
    GSController.Sleep(6);
    local r2 = this.RunReader(c.lc.wd, c.lc.ed);                       // g2 NOR -> carry
    return [r0, r1, r2];
}

function StageBCarryMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("STBC build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastYb = BASE + 3*BAND + DY_B;
    this.Prepare(A_BX - 2, BASE - 2, C_EAST + 1, lastYb + 2);

    local copies = [];
    for (local k = 0; k < 4; k++) copies.append(this.BuildCopy(BASE + k*BAND));
    this.Say("STBC built4");

    local r00 = this.RunCase(copies[0], 0, 0);
    this.Say("c00 " + r00[0] + "/" + r00[1] + "/" + r00[2]);
    local r01 = this.RunCase(copies[1], 0, 1);
    this.Say("c01 " + r01[2]);
    local r10 = this.RunCase(copies[2], 1, 0);
    this.Say("c10 " + r10[2]);
    local r11 = this.RunCase(copies[3], 1, 1);

    // Encode SHORT: the four g2 (carry output) final x. Judge: x > C_SIG => carry 1.
    local nm = "STBC s" + C_SIG + " " + r00[2] + " " + r01[2] + " " + r10[2] + " " + r11[2];
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function StageBCarryMain::Save() { return {}; }
function StageBCarryMain::Load(version, data) {}
