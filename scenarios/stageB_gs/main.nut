/*
 * stageB: a FIXED HALF-ADDER SUM bit (a XOR b) as a 6-gate NOR network on trains. Proves the
 * norchain fixed signal-free coupling composes through fan-out (a duplicated driver) and
 * reconvergent fan-in (g3 reads two couplings), past the 2-gate norchain and 3-gate stageA.
 *
 * NETWORK (merge-free; the fan-out driver NOR(a,b) is DUPLICATED as g0a, g0b so every gate
 * drives exactly ONE consumer block, exactly the proven norchain coupling):
 *     g0a = NOR(a, b)  -> n1a       (drives g1)
 *     g0b = NOR(a, b)  -> n1b       (drives g2)
 *     g1  = NOR(a, n1a) -> n2       (reads primary a + coupling n1a; drives g3)
 *     g2  = NOR(b, n1b) -> n3       (reads primary b + coupling n1b; drives g3)
 *     g3  = NOR(n2, n3) -> n4       (reads couplings n2 AND n3 into one block; drives g4)
 *     g4  = NOR(n4)     -> y        (a NOT; the output)
 * Expected y over (a,b) = 00,01,10,11: 0,1,1,0 = XOR, judged from RAW g4 reader x.
 *
 * GEOMETRY reused VERBATIM from norchain / stageA (all PROVEN):
 *   - a bit is train-presence on a protected through-block; a reader passes a normal block
 *     signal iff its input block is empty (== NOR of the present inputs).
 *   - BuildSignal(tile, front) permits travel FROM front INTO tile, so an eastbound reader
 *     needs front = SIG-1; the input block is terminated by a SECOND signal.
 *   - a PASSING driver reader is FROZEN the instant it clears its terminating signal, on its
 *     coupling tile CPL; a SHORT PURE-VERTICAL signal-free spur joins CPL into the consumer's
 *     input block (which straddles CPL), merging the two blocks. Driver output 1 == a train in
 *     the consumer's input block.
 *   - the reconvergence g3 = NOR(n2, n3) is placed BETWEEN its drivers: g1 directly above
 *     (spur DOWN), g2 directly below (spur UP), so both couplings are short and adjacent. The
 *     g3 -> g4 output spur is at a far-east column kept clear of the intervening lanes.
 *
 * NO per-gate train is re-parked or disposed between reads: per input combo ONE fresh network
 * copy is built at its own band of rows, primary inputs pre-parked ONCE, then the six gate
 * readers run in topological order (each frozen on its CPL if it passes). The four combos are
 * SEPARATE physical copies (teardown on a coupled junction hangs the script, per norchain).
 *
 * Coordinates (verified collision-free; columns absolute, rows = combo BASE + per-gate dy):
 *   gate  dy  BX  SIG taps        SIGT CPL EAST   role
 *   g0a    0  30  36  [37a,38b]    39   40  46     root NOR(a,b) -> n1a (spur down to g1)
 *   g1     3  32  38  [39a,40n1a]  41   42  48     reads a + n1a -> n2  (spur down to g3)
 *   g3     6  35  41  [42n2,43n3]  44   50  56     reads n2 + n3 -> n4  (spur down to g4)
 *   g2     9  33  39  [40b,41n1b]  42   43  49     reads b + n1b -> n3  (spur UP to g3)
 *   g0b   12  31  37  [38a,39b]    40   41  47     root NOR(a,b) -> n1b (spur UP to g2)
 *   g4    15  43  49  [50n4]       51   52  55     NOT(n4) -> y (output; reads via spur down)
 */

// ---- absolute column geometry, shared by every combo copy (verified collision-free) ----
// g0a
A_BX <- 30; A_SIG <- 36; A_TA <- 37; A_TB <- 38; A_SIGT <- 39; A_CPL <- 40; A_EAST <- 46;
// g1
B_BX <- 32; B_SIG <- 38; B_TA <- 39; B_TN <- 40; B_SIGT <- 41; B_CPL <- 42; B_EAST <- 48;
// g3 (the reconvergence; CPL pushed far east to clear the g3->g4 output spur over the
// intervening lanes, so its freeze block needs a second terminating signal C_TERM2 to be a
// proper through block, east of CPL and west of the east depot).
C_BX <- 35; C_SIG <- 41; C_T2 <- 42; C_T3 <- 43; C_SIGT <- 44; C_CPL <- 50; C_TERM2 <- 51; C_EAST <- 56;
// g2
D_BX <- 33; D_SIG <- 39; D_TB <- 40; D_TN <- 41; D_SIGT <- 42; D_CPL <- 43; D_EAST <- 49;
// g0b
E_BX <- 31; E_SIG <- 37; E_TA <- 38; E_TB <- 39; E_SIGT <- 40; E_CPL <- 41; E_EAST <- 47;
// g4
F_BX <- 43; F_SIG <- 49; F_TN <- 50; F_SIGT <- 51; F_CPL <- 52; F_EAST <- 55;

// per-gate row offsets within a combo band
DY_A <- 0; DY_B <- 3; DY_C <- 6; DY_D <- 9; DY_E <- 12; DY_F <- 15;

BASE <- 30;   // first combo's g0a lane row
BAND <- 22;   // rows between successive combo bands (16 span + slack)

class StageBMain extends GSController {
    company = null; eng = null;
    constructor() {}
}

function StageBMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function StageBMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function StageBMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function StageBMain::Say(s) { GSCompany.SetName(s); }
function StageBMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Build a horizontal gate lane (track + 2 depots + reader signal + terminating signal). If
// cpl > sigt the lane runs east as far as cpl (filler straight track, one block) so the freeze
// tile sits past the terminating signal. term2x > 0 adds a THIRD signal east of the freeze tile
// so the freeze block (between sigtx and term2x) is a proper THROUGH block: a normal signal in
// front of a dead-end block stays red, so a gate whose CPL sits far past its terminating signal
// (g3, pushed to clear the output spur) needs its reader to pass sigtx into a through block to
// reliably reach and freeze on CPL. Returns {wd, ed}.
function StageBMain::BuildLane(bx, eastx, gy, sigx, sigtx, term2x) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
    local wd = GSMap.GetTileIndex(bx - 1, gy);
    GSRail.BuildRailDepot(wd, GSMap.GetTileIndex(bx, gy));
    local ed = GSMap.GetTileIndex(eastx, gy);
    GSRail.BuildRailDepot(ed, GSMap.GetTileIndex(eastx - 1, gy));
    GSRail.BuildSignal(GSMap.GetTileIndex(sigx, gy),  GSMap.GetTileIndex(sigx - 1, gy),  GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(sigtx, gy), GSMap.GetTileIndex(sigtx - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    if (term2x > 0)
        GSRail.BuildSignal(GSMap.GetTileIndex(term2x, gy), GSMap.GetTileIndex(term2x - 1, gy), GSRail.SIGNALTYPE_NORMAL);
    return { wd = wd, ed = ed };
}

// A feeder depot just NORTH of tap tile (tx, gy), joined into the lane.
function StageBMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// A pure-vertical signal-free coupling spur in column cplx from row gya to row gyb (either
// order), with corner pieces joining each end lane (exactly norchain's spur).
function StageBMain::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}

// Park an input train on tile (tx, gy) from feeder depot d. Freeze it on the tap.
function StageBMain::ParkInput(d, tx, gy) {
    local v = GSVehicle.BuildVehicle(d, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, gy), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v) && GSMap.GetTileX(GSVehicle.GetLocation(v))==tx && GSMap.GetTileY(GSVehicle.GetLocation(v))==gy) { GSVehicle.StartStopVehicle(v); break; }
    }
    return v;
}

// Run a gate reader on row gy from depot wd toward ed; freeze the instant it clears the
// terminating signal (x >= cpl) OR it passed the reader signal then left row gy (started down
// the spur). A HELD reader (input occupied) rests at sigx-1 on gy and is not frozen. Returns x.
function StageBMain::RunFreeze(wd, ed, gy, sigx, cpl) {
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

// Run the final gate reader (no freeze); record where it stops. Returns final x.
function StageBMain::RunReader(wd, ed) {
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

// Build one independent network copy at combo base row gy. Returns a table of run handles.
function StageBMain::BuildCopy(gy) {
    local ya = gy + DY_A, yb = gy + DY_B, yc = gy + DY_C, yd = gy + DY_D, ye = gy + DY_E, yf = gy + DY_F;
    local la = this.BuildLane(A_BX, A_EAST, ya, A_SIG, A_SIGT, 0);
    local lb = this.BuildLane(B_BX, B_EAST, yb, B_SIG, B_SIGT, 0);
    local lc = this.BuildLane(C_BX, C_EAST, yc, C_SIG, C_SIGT, C_TERM2);
    local ld = this.BuildLane(D_BX, D_EAST, yd, D_SIG, D_SIGT, 0);
    local le = this.BuildLane(E_BX, E_EAST, ye, E_SIG, E_SIGT, 0);
    local lf = this.BuildLane(F_BX, F_EAST, yf, F_SIG, F_SIGT, 0);
    // primary input feeders: g0a a@A_TA b@A_TB ; g0b a@E_TA b@E_TB ; g1 a@B_TA ; g2 b@D_TB.
    local fa = { aa = this.FeederDepot(A_TA, ya), ab = this.FeederDepot(A_TB, ya),
                 ea = this.FeederDepot(E_TA, ye), eb = this.FeederDepot(E_TB, ye),
                 b1a = this.FeederDepot(B_TA, yb), d2b = this.FeederDepot(D_TB, yd) };
    // coupling spurs (driver CPL column, driver row -> consumer row):
    this.BuildSpur(A_CPL, ya, yb);   // g0a -> g1  (down)
    this.BuildSpur(E_CPL, ye, yd);   // g0b -> g2  (up)
    this.BuildSpur(B_CPL, yb, yc);   // g1  -> g3  (down)
    this.BuildSpur(D_CPL, yd, yc);   // g2  -> g3  (up)
    this.BuildSpur(C_CPL, yc, yf);   // g3  -> g4  (down, far-east column 50, clears g2/g0b)
    return { gy = gy, ya = ya, yb = yb, yc = yc, yd = yd, ye = ye, yf = yf,
             la = la, lb = lb, lc = lc, ld = ld, le = le, lf = lf, fa = fa };
}

// Run one combo: pre-park primary inputs, then run the six readers in topological order.
// Returns [g0a, g0b, g1, g2, g3, g4] final x.
function StageBMain::RunCase(c, a, b) {
    // primary inputs (each a separate train on its own tap)
    if (a) this.ParkInput(c.fa.aa, A_TA, c.ya);
    if (b) this.ParkInput(c.fa.ab, A_TB, c.ya);
    if (a) this.ParkInput(c.fa.ea, E_TA, c.ye);
    if (b) this.ParkInput(c.fa.eb, E_TB, c.ye);
    if (a) this.ParkInput(c.fa.b1a, B_TA, c.yb);
    if (b) this.ParkInput(c.fa.d2b, D_TB, c.yd);
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
    GSController.Sleep(6);
    local r4 = this.RunReader(c.lf.wd, c.lf.ed);
    return [r0a, r0b, r1, r2, r3, r4];
}

function StageBMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("STGB build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastYf = BASE + 3*BAND + DY_F;
    this.Prepare(A_BX - 2, BASE - 2, F_EAST + 1, lastYf + 2);

    local copies = [];
    for (local k = 0; k < 4; k++) copies.append(this.BuildCopy(BASE + k*BAND));
    this.Say("STGB built4");

    local r00 = this.RunCase(copies[0], 0, 0);
    this.Say("b00 " + r00[4] + "/" + r00[5]);
    local r01 = this.RunCase(copies[1], 0, 1);
    this.Say("b01 " + r01[4] + "/" + r01[5]);
    local r10 = this.RunCase(copies[2], 1, 0);
    this.Say("b10 " + r10[4] + "/" + r10[5]);
    local r11 = this.RunCase(copies[3], 1, 1);

    // Encode SHORT: the four g4 (XOR output) final x. Judge: x > F_SIG => output 1.
    local nm = "STGB s" + F_SIG + " " + r00[5] + " " + r01[5] + " " + r10[5] + " " + r11[5];
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function StageBMain::Save() { return {}; }
function StageBMain::Load(version, data) {}
