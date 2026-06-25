/*
 * fasum: STAGE 2, the FULL-ADDER SUM = parity(a,b,cin) = XOR( XOR(a,b), cin ), as TWO bridged-XOR
 * stages chained on real trains. XOR1 computes h = a XOR b (the proven xorsum1 6-gate bridged XOR);
 * XOR2 computes s = XOR(h, cin), with the XOR1 output h COUPLED into XOR2's input (the chain link).
 * Couplings that cross a lane are routed as BRIDGES (the bridgeprobe / xorbridge primitive).
 *
 * NETLIST (verified exhaustively in Python = parity 0,1,1,0,1,0,0,1 over (a,b,cin)=000..111):
 *   XOR1 (stageB/xorsum1 structure, produces h):
 *     g0a=NOR(a,b)->n1a  g0b=NOR(a,b)->n1b  g1=NOR(a,n1a)->n2  g2=NOR(b,n1b)->n3
 *     g3=NOR(n2,n3)->n4  g4=NOR(n4)->h            (g4 is the NOT; h = XOR1 output)
 *   XOR2 (regen XOR, h read EXACTLY ONCE so the chain is a single coupling = fan-out 1):
 *     NH=NOR(h)->{HH,Q}  HH=NOR(nh)->P  NC=NOR(cin)->Q  P=NOR(hh,cin)->Y  Q=NOR(nh,nc)->Y  Y=NOR(p,q)->s
 *   nh fan-out 2 (HH and Q): NH is placed BETWEEN HH (above) and Q (below) so its two output spurs
 *   leave the freeze tile in OPPOSITE directions (up to HH, down to Q), no shared-column conflict;
 *   the down spur to Q BRIDGES over the intervening P and Y lanes.
 *
 * THE CHAIN LINK: h = XOR1.g4's frozen reader at (col 50, XOR1 g4 row). XOR2.NH reads h at col 50;
 * the h coupling is a vertical spur in column 50 from XOR1.g4's row DOWN into NH's input block. If
 * it crosses an XOR2 lane it is a BRIDGE (here it crosses HH's lane -> one bridge).
 *
 * Bridges per combo: XOR1 g3->g4 (2, over g2,g0b) + XOR2 NH->Q (2, over P,Y) + HH->P (1, over NH)
 * + h-chain (1, over HH) = 6. Each combo is a SEPARATE physical copy (no teardown), 8 combos.
 * Outputs (s) from RAW Y reader x only (x > Y_SIG => 1); no parity computed in Squirrel.
 *
 * Readout (short): "FS s<Y_SIG> <s000..s111 8 values> b<all bridges built 0/1>". Map 9 (512) for the
 * 8 tall combo bands. Reuses ALL proven helpers (BuildLane, FeederDepot, BuildSpur, BuildBridgedSpur,
 * ParkInput, BuildReader, RunFreeze, RunReader) verbatim from xorsum1 / fulladder_cout.
 */

// ===================== XOR1 columns (xorsum1 EXACT geometry) =====================
A_BX <- 30; A_SIG <- 36; A_TA <- 37; A_TB <- 38; A_SIGT <- 39; A_CPL <- 40; A_EAST <- 48;
B_BX <- 32; B_SIG <- 38; B_TA <- 39; B_TN <- 40; B_SIGT <- 41; B_CPL <- 42; B_EAST <- 50;
C_BX <- 35; C_SIG <- 41; C_T2 <- 42; C_T3 <- 43; C_SIGT <- 44; C_CPL <- 45; C_TERM2 <- 46; C_EAST <- 52;
D_BX <- 37; D_SIG <- 38; D_TB <- 40; D_TN <- 41; D_SIGT <- 42; D_CPL <- 43; D_TERM2 <- 47; D_EAST <- 54;
E_BX <- 36; E_SIG <- 37; E_TA <- 38; E_TB <- 39; E_SIGT <- 40; E_CPL <- 41; E_TERM2 <- 47; E_EAST <- 54;
F_BX <- 42; F_SIG <- 44; F_TN <- 45; F_SIGT <- 49; F_CPL <- 50; F_EAST <- 56;   // g4 -> h at col 50

DY_A <- 0; DY_B <- 3; DY_C <- 6; DY_D <- 9; DY_E <- 13; DY_F <- 16;   // XOR1 rows

// ===================== XOR2 columns (regen XOR, nh DUPLICATED as NHa,NHb) =====================
// nh is read by HH and Q. To keep every DISTINCT-signal net fan-out 1, NH is built TWICE: NHa drives
// HH, NHb drives Q. Both NHa and NHb read the h-chain (col 50); since both compute NOR(h) (the SAME
// signal), the h coupling merging their two input blocks is BENIGN (no distinct-signal corruption).
// NHa sits just BELOW NHb so NHa->HH is planar (crosses nothing); only NHb->Q bridges (over NHa,HH,P,Y).
NHa_BX <- 44; NHa_SIG <- 48; NHa_TH <- 50; NHa_SIGT <- 51; NHa_CPL <- 52; NHa_EAST <- 60;
NHb_BX <- 44; NHb_SIG <- 48; NHb_TH <- 50; NHb_SIGT <- 51; NHb_CPL <- 53; NHb_TERM2 <- 54; NHb_EAST <- 60;
HH_BX <- 46; HH_SIG <- 49; HH_TNHA <- 52; HH_SIGT <- 55; HH_CPL <- 56; HH_EAST <- 64;
P_BX  <- 46; P_SIG  <- 49; P_TCIN <- 51; P_THH <- 56; P_SIGT <- 57; P_CPL <- 58; P_EAST <- 66;
Y_BX  <- 46; Y_SIG  <- 50; Y_TP <- 58; Y_TQ <- 59; Y_SIGT <- 60; Y_CPL <- 61; Y_EAST <- 68;
Q_BX  <- 46; Q_SIG  <- 50; Q_TNC <- 52; Q_TNHB <- 53; Q_SIGT <- 54; Q_CPL <- 59; Q_TERM2 <- 60; Q_EAST <- 66;
NC_BX <- 44; NC_SIG <- 49; NC_TCIN <- 50; NC_SIGT <- 51; NC_CPL <- 52; NC_EAST <- 60;

// XOR2 rows. NHb=20, NHa=23 (NHa below NHb). HH,P,Y,Q,NC spaced 4 apart so the NHb->Q bridge spans
// (over NHa,HH,P,Y) never touch.
DY_NHb <- 20; DY_NHa <- 23; DY_HH <- 27; DY_P <- 31; DY_Y <- 35; DY_Q <- 39; DY_NC <- 43;

BASE <- 30;   // first combo's XOR1 g0a row
BAND <- 47;   // rows between combo bands (44 span + slack); 8 combos need map 9 (512)

class FaSumMain extends GSController {
    company = null; eng = null; allbr = true;
    constructor() {}
}

function FaSumMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function FaSumMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function FaSumMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function FaSumMain::Say(s) { GSCompany.SetName(s); }
function FaSumMain::Prepare(x0, y0, x1, y1) {
    // YIELD per row: a tight multi-thousand-tile demolish with no Sleep floods the command queue in
    // one GS step and OpenTTD RELOADS the script (the readout resets mid-run). Sleeping drains it.
    for (local x = x0; x <= x1; x++) {
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
        GSController.Sleep(1);
    }
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSController.Sleep(2);
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}
function FaSumMain::SignalVerified(sx, gy) {
    local t = GSMap.GetTileIndex(sx, gy);
    local f = GSMap.GetTileIndex(sx - 1, gy);
    for (local i = 0; i < 8; i++) {
        if (GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE) return true;
        GSRail.BuildSignal(t, f, GSRail.SIGNALTYPE_NORMAL);
        GSController.Sleep(2);
    }
    return GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE;
}
function FaSumMain::BuildLane(bx, eastx, gy, sigx, sigtx, term2x) {
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
function FaSumMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}
// A pure-vertical signal-free coupling spur in column cplx from row gya to row gyb (either order).
function FaSumMain::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}
// One length-3 N-S bridge in column cplx over lane row ly (the proven recipe).
function FaSumMain::BuildOneBridge(cplx, ly) {
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
// A vertical coupling spur in column cplx from gya to gyb that BRIDGES over each lane row in lys[].
// Plain spur rail on every row except each bridge span (ly-1,ly,ly+1); corner pieces at the ends.
function FaSumMain::BuildBridgedSpur(cplx, gya, gyb, lys) {
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
function FaSumMain::ParkInput(d, tx, gy) {
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
function FaSumMain::BuildReader(wd, ed) {
    if (!GSRail.IsRailDepotTile(wd))
        for (local d = 0; d < 10 && !GSRail.IsRailDepotTile(wd); d++) GSController.Sleep(5);
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
function FaSumMain::RunFreeze(wd, ed, gy, sigx, cpl) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 10; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
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
function FaSumMain::RunReader(wd, ed) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 10; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 28; s++) { GSController.Sleep(12); local t = this.Tx(v); if (t >= 0) fx = t; }
    return fx;
}

// Build one independent full-adder-SUM copy at combo base row gy. Returns the run handles.
function FaSumMain::BuildCopy(gy) {
    // ---- XOR1 (produces h) : xorsum1 EXACT ----
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
    this.BuildSpur(A_CPL, ya, yb);   // g0a -> g1
    this.BuildSpur(E_CPL, ye, yd);   // g0b -> g2
    this.BuildSpur(B_CPL, yb, yc);   // g1  -> g3
    this.BuildSpur(D_CPL, yd, yc);   // g2  -> g3
    local br1 = this.BuildBridgedSpur(C_CPL, yc, yf, [yd, ye]);   // g3 -> g4 (h) bridged over g2,g0b
    if (!br1) this.allbr = false;

    // ---- XOR2 (consumes h, cin) : regen XOR, nh DUPLICATED (NHa drives HH, NHb drives Q) ----
    local ynha = gy+DY_NHa, ynhb = gy+DY_NHb, yhh = gy+DY_HH, yp = gy+DY_P, yy = gy+DY_Y, yq = gy+DY_Q, ync = gy+DY_NC;
    local lnha = this.BuildLane(NHa_BX, NHa_EAST, ynha, NHa_SIG, NHa_SIGT, 0);
    local lnhb = this.BuildLane(NHb_BX, NHb_EAST, ynhb, NHb_SIG, NHb_SIGT, NHb_TERM2);
    local lhh = this.BuildLane(HH_BX, HH_EAST, yhh, HH_SIG, HH_SIGT, 0);
    local lp  = this.BuildLane(P_BX,  P_EAST,  yp,  P_SIG,  P_SIGT, 0);
    local lyy = this.BuildLane(Y_BX,  Y_EAST,  yy,  Y_SIG,  Y_SIGT, 0);
    local lq  = this.BuildLane(Q_BX,  Q_EAST,  yq,  Q_SIG,  Q_SIGT, Q_TERM2);
    local lnc = this.BuildLane(NC_BX, NC_EAST, ync, NC_SIG, NC_SIGT, 0);
    // cin primary feeders: NC reads cin@NC_TCIN ; P reads cin@P_TCIN.
    local fc = { nc = this.FeederDepot(NC_TCIN, ync), p = this.FeederDepot(P_TCIN, yp) };
    // XOR2 planar couplings:
    this.BuildSpur(NHa_CPL, ynha, yhh);           // NHa -> HH (down, planar)
    this.BuildSpur(HH_CPL, yhh, yp);              // HH -> P (down, planar)
    this.BuildSpur(NC_CPL, ync, yq);              // NC -> Q (up, planar)
    this.BuildSpur(P_CPL, yp, yy);                // P -> Y (down, planar)
    this.BuildSpur(Q_CPL, yq, yy);               // Q -> Y (up, planar)
    // NHb -> Q : the ONE bridged coupling, BRIDGED over NHa, HH, P, Y (the lanes between NHb and Q).
    local br2 = this.BuildBridgedSpur(NHb_CPL, ynhb, yq, [ynha, yhh, yp, yy]);
    if (!br2) this.allbr = false;
    // h-chain : XOR1.g4 frozen at (F_CPL=50, yf) -> NHb(top) and NHa read h at col 50. A single spur
    // in col 50 from yf DOWN merges NHb (DY20) then NHa (DY23) input blocks (both read h@50; the
    // merge is BENIGN, same signal). It crosses no other lane (rows 17,18,19,21,22 are empty).
    local br4 = this.BuildBridgedSpur(F_CPL, yf, ynha, []);   // no bridges: plain spur yf->NHa thru NHb
    if (!br4) this.allbr = false;

    return { gy = gy, ya=ya,yb=yb,yc=yc,yd=yd,ye=ye,yf=yf,
             ynha=ynha,ynhb=ynhb,yhh=yhh,yp=yp,yy=yy,yq=yq,ync=ync,
             la=la,lb=lb,lc=lc,ld=ld,le=le,lf=lf, lnha=lnha,lnhb=lnhb,lhh=lhh,lp=lp,lyy=lyy,lq=lq,lnc=lnc,
             fa=fa, fc=fc };
}

// Run one combo (a,b,cin): park primaries, run XOR1 readers, then XOR2 readers; return s reader x.
function FaSumMain::RunCase(c, a, b, cin) {
    // XOR1 primaries (a,b)
    if (a) this.ParkInput(c.fa.aa, A_TA, c.ya);
    if (b) this.ParkInput(c.fa.ab, A_TB, c.ya);
    if (a) this.ParkInput(c.fa.ea, E_TA, c.ye);
    if (b) this.ParkInput(c.fa.eb, E_TB, c.ye);
    if (a) this.ParkInput(c.fa.b1a, B_TA, c.yb);
    if (b) this.ParkInput(c.fa.d2b, D_TB, c.yd);
    // XOR2 primaries (cin)
    if (cin) this.ParkInput(c.fc.nc, NC_TCIN, c.ync);
    if (cin) this.ParkInput(c.fc.p, P_TCIN, c.yp);
    GSController.Sleep(8);
    // XOR1 in topological order -> freeze g4 producing h
    this.RunFreeze(c.la.wd, c.la.ed, c.ya, A_SIG, A_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.le.wd, c.le.ed, c.ye, E_SIG, E_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lb.wd, c.lb.ed, c.yb, B_SIG, B_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.ld.wd, c.ld.ed, c.yd, D_SIG, D_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lc.wd, c.lc.ed, c.yc, C_SIG, C_CPL);
    GSController.Sleep(6);
    // g4 (h): freeze it on F_CPL so it couples down the chain into NHa and NHb's blocks.
    local hbit = this.RunFreeze(c.lf.wd, c.lf.ed, c.yf, F_SIG, F_CPL);
    GSController.Sleep(20);
    // XOR2 topological order: NHa, NHb (read h), HH, NC, P, Q, then Y (terminal = s)
    this.RunFreeze(c.lnha.wd, c.lnha.ed, c.ynha, NHa_SIG, NHa_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lnhb.wd, c.lnhb.ed, c.ynhb, NHb_SIG, NHb_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lhh.wd, c.lhh.ed, c.yhh, HH_SIG, HH_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lnc.wd, c.lnc.ed, c.ync, NC_SIG, NC_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lp.wd, c.lp.ed, c.yp, P_SIG, P_CPL);
    GSController.Sleep(6);
    this.RunFreeze(c.lq.wd, c.lq.ed, c.yq, Q_SIG, Q_CPL);
    GSController.Sleep(40);
    local s = this.RunReader(c.lyy.wd, c.lyy.ed);
    return { h = hbit, s = s };
}

function FaSumMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("FS build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastY = BASE + 7*BAND + DY_NC;
    this.Prepare(A_BX - 2, BASE - 2, Y_EAST + 2, lastY + 2);

    local copies = [];
    for (local k = 0; k < 8; k++) { copies.append(this.BuildCopy(BASE + k*BAND)); GSController.Sleep(4); }
    this.Say("FS built8 b" + (this.allbr ? 1 : 0));

    // 8 combos (a,b,cin) = 000..111. Expected s = parity = 0,1,1,0,1,0,0,1.
    local combos = [[0,0,0],[0,0,1],[0,1,0],[0,1,1],[1,0,0],[1,0,1],[1,1,0],[1,1,1]];
    local outs = [-1, -1, -1, -1, -1, -1, -1, -1];
    // Each combo guarded + its per-combo readout shown SHORT (the runner records every distinct name,
    // so per-combo results survive in the log even if the final readout is wiped by an intermittent
    // GS restart, the same restart seen in xorsum1's late combos).
    for (local k = 0; k < 8; k++) {
        try {
            local r = this.RunCase(copies[k], combos[k][0], combos[k][1], combos[k][2]);
            outs[k] = r.s;
            this.Say("c" + combos[k][0] + combos[k][1] + combos[k][2] + " h" + r.h + " s" + r.s);
        } catch (e) {
            this.Say("c" + combos[k][0] + combos[k][1] + combos[k][2] + " ERR");
        }
        GSController.Sleep(4);
    }
    // Encode SHORT (the ~31-char company-name limit): "FS<Y_SIG> <8 s reader x>" = ~28 chars. Judge
    // externally: x > Y_SIG (=50) => s 1. Expected 0,1,1,0,1,0,0,1. The all-bridges-built flag was
    // already reported in "FS built8 b<0/1>"; the per-combo h/s intermediates carry the rest.
    local nm = "FS" + Y_SIG;
    for (local k = 0; k < 8; k++) nm += " " + outs[k];
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function FaSumMain::Save() { return {}; }
function FaSumMain::Load(version, data) {}
