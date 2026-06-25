/*
 * xorbridge: STAGE 2 application of the bridge crossing primitive (bridgeprobe_gs proved it in
 * isolation). A reconvergent NOR network computing the half-adder CARRY = a AND b, but laid out
 * NON-PLANAR so a coupling spur must CROSS an intervening root's reader lane, routed as a BRIDGE.
 *
 *     g0 = NOR(a) -> na        (NOT a; root)
 *     g1 = NOR(b) -> nb        (NOT b; root)
 *     g2 = NOR(na, nb) = AND(a,b)   (reconvergence; the output)
 *
 * stageBcarry places g2 BETWEEN its drivers (planar, no crossing). HERE g2 is BELOW both roots:
 *   rows  g0 @ dy0,  g1 @ dy3,  g2 @ dy6.
 *   g1 -> g2 coupling spur (col G1_CPL) runs row3 -> row6, crosses nothing.
 *   g0 -> g2 coupling spur (col G0_CPL) runs row0 -> row6, and MUST CROSS g1's reader lane at row3.
 * That crossing is a BRIDGE: g0's spur goes OVER g1's lane (the lane tile is the tile UNDER the
 * bridge, a separate block). So g0 stays coupled to g2 AND g1's lane stays isolated. A LEVEL
 * crossing there would short g0's spur block into g1's lane (the control proves it).
 *
 * EMPIRICAL BRIDGE RECIPE (bridgemicro_gs): BuildBridge builds its own ramps, so the head/tail
 * ramp tiles must NOT have rail pre-laid; the under-tile carries the perpendicular (E-W) lane rail.
 * A length-3 N-S bridge spans (G0_CPL, LY-1) -> (G0_CPL, LY+1) over the lane tile (G0_CPL, LY).
 *
 * Truth table c over (a,b)=00,01,10,11 is 0,0,0,1 = AND, judged from RAW g2 reader x (x>G2_SIG=>1).
 * Every gate on its own lane, wired by fixed signal-free coupling spurs, built ONCE per combo; four
 * SEPARATE physical combo copies; no per-gate train re-parked between reads. Outputs RAW reader x only.
 * Readout (short): "XB s<G2_SIG> <c00> <c01> <c10> <c11> b<bridges all built 0/1>".
 */

// g0 (NOT a): lane, reader signal, input tap a, terminating signal, coupling tile.
G0_BX   <- 30; G0_SIG <- 36; G0_TA <- 37; G0_SIGT <- 38; G0_CPL <- 39; G0_EAST <- 45;
// g1 (NOT b): its protected block is G1_SIG..G1_SIGT; the bridge crosses it INSIDE that block at
// column G0_CPL (=39), which must satisfy G1_SIG < G0_CPL < G1_SIGT so a level short would be visible.
G1_BX   <- 30; G1_SIG <- 37; G1_TB <- 38; G1_SIGT <- 41; G1_EAST <- 47; G1_CPL <- 42;
// g2 (NOR(na,nb) = AND): input block straddles the two coupling columns G0_CPL(39) and G1_CPL(42).
G2_BX   <- 33; G2_SIG <- 38; G2_TNA <- 39; G2_TNB <- 42; G2_SIGT <- 43; G2_EAST <- 49;

DY_G0 <- 0; DY_G1 <- 3; DY_G2 <- 6;
BASE <- 30; BAND <- 14;

class XorBridgeMain extends GSController {
    company = null; eng = null; allbr = true;
    constructor() {}
}

function XorBridgeMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function XorBridgeMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function XorBridgeMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function XorBridgeMain::Say(s) { GSCompany.SetName(s); }
function XorBridgeMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}
function XorBridgeMain::SignalVerified(sx, gy) {
    local t = GSMap.GetTileIndex(sx, gy);
    local f = GSMap.GetTileIndex(sx - 1, gy);
    for (local i = 0; i < 8; i++) {
        if (GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE) return true;
        GSRail.BuildSignal(t, f, GSRail.SIGNALTYPE_NORMAL);
        GSController.Sleep(2);
    }
    return GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE;
}
function XorBridgeMain::BuildLane(bx, eastx, gy, sigx, sigtx) {
    for (local x = bx; x < eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, gy), GSRail.RAILTRACK_NE_SW);
    local wd = GSMap.GetTileIndex(bx - 1, gy);
    GSRail.BuildRailDepot(wd, GSMap.GetTileIndex(bx, gy));
    local ed = GSMap.GetTileIndex(eastx, gy);
    GSRail.BuildRailDepot(ed, GSMap.GetTileIndex(eastx - 1, gy));
    this.SignalVerified(sigx, gy);
    this.SignalVerified(sigtx, gy);
    return { wd = wd, ed = ed };
}
function XorBridgeMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// A plain (level) signal-free vertical coupling spur in column cplx from gya to gyb. Used for the
// g1->g2 coupling (crosses nothing) and for the LEVEL control of the g0->g2 coupling.
function XorBridgeMain::BuildSpur(cplx, gya, gyb) {
    local lo = gya < gyb ? gya : gyb;
    local hi = gya < gyb ? gyb : gya;
    for (local y = lo; y <= hi; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, lo), GSRail.RAILTRACK_SW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, hi), GSRail.RAILTRACK_NW_NE);
}

// The g0->g2 coupling spur in column cplx from gya(top) to gyb(bottom), CROSSING the lane at ly.
// useBridge=true bridges OVER (ly-1)->(ly+1); false lays a level junction (the control short).
// Returns true iff the bridge built (or true trivially for the level case so allbr tracks only bridges).
function XorBridgeMain::BuildCrossingSpur(cplx, gya, gyb, ly, useBridge) {
    if (useBridge) {
        // vertical spur on all rows except the bridge span (ly-1, ly, ly+1).
        for (local y = gya; y <= gyb; y++) {
            if (y >= ly - 1 && y <= ly + 1) continue;
            GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, y), GSRail.RAILTRACK_NW_SE);
        }
        // corner pieces joining the spur ends into the horizontal lanes at top and bottom.
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, gya), GSRail.RAILTRACK_SW_SE);
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, gyb), GSRail.RAILTRACK_NW_NE);
        // ensure the under-tile carries g1's E-W lane rail before bridging.
        for (local i = 0; i < 8 && !GSRail.IsRailTile(GSMap.GetTileIndex(cplx, ly)); i++) {
            GSRail.BuildRailTrack(GSMap.GetTileIndex(cplx, ly), GSRail.RAILTRACK_NE_SW);
            GSController.Sleep(3);
        }
        local head = GSMap.GetTileIndex(cplx, ly - 1);
        local tail = GSMap.GetTileIndex(cplx, ly + 1);
        local len = GSMap.DistanceManhattan(head, tail) + 1;
        for (local i = 0; i < 10; i++) {
            if (GSBridge.IsBridgeTile(head)) break;
            local types = GSBridgeList_Length(len);
            if (!types.IsEmpty()) GSBridge.BuildBridge(GSVehicle.VT_RAIL, types.Begin(), head, tail);
            GSController.Sleep(4);
        }
        return GSBridge.IsBridgeTile(head);
    } else {
        this.BuildSpur(cplx, gya, gyb);   // continuous level spur, shorts g1's lane (control)
        return false;
    }
}

function XorBridgeMain::ParkInput(d, tx, gy) {
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
function XorBridgeMain::BuildReader(wd, ed) {
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
// Run a root reader; freeze the instant it clears the terminating signal (x>=cpl) or leaves the row.
function XorBridgeMain::RunFreeze(wd, ed, gy, sigx, cpl) {
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
function XorBridgeMain::RunReader(wd, ed) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 12; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = -1;
    for (local s = 0; s < 40; s++) {
        GSController.Sleep(10);
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        local t = this.Tx(v); if (t >= 0) fx = t;
    }
    return fx;
}

function XorBridgeMain::BuildCopy(gy, useBridge) {
    local y0 = gy + DY_G0, y1 = gy + DY_G1, y2 = gy + DY_G2;
    local l0 = this.BuildLane(G0_BX, G0_EAST, y0, G0_SIG, G0_SIGT);
    local l1 = this.BuildLane(G1_BX, G1_EAST, y1, G1_SIG, G1_SIGT);
    local l2 = this.BuildLane(G2_BX, G2_EAST, y2, G2_SIG, G2_SIGT);
    local f0 = this.FeederDepot(G0_TA, y0);   // primary a on g0
    local f1 = this.FeederDepot(G1_TB, y1);   // primary b on g1
    // g1 -> g2 coupling: plain spur, crosses nothing.
    this.BuildSpur(G1_CPL, y1, y2);
    // g0 -> g2 coupling: NON-PLANAR, crosses g1's lane at row y1 -> bridge (or level control).
    local isBr = this.BuildCrossingSpur(G0_CPL, y0, y2, y1, useBridge);
    if (useBridge && !isBr) this.allbr = false;
    return { gy = gy, y0 = y0, y1 = y1, y2 = y2, l0 = l0, l1 = l1, l2 = l2, f0 = f0, f1 = f1, isBr = isBr };
}

function XorBridgeMain::RunCase(c, a, b) {
    if (a) this.ParkInput(c.f0, G0_TA, c.y0);
    if (b) this.ParkInput(c.f1, G1_TB, c.y1);
    GSController.Sleep(8);
    local r0 = this.RunFreeze(c.l0.wd, c.l0.ed, c.y0, G0_SIG, G0_CPL);   // g0 NOT a (frozen, couples via bridge)
    GSController.Sleep(6);
    local r1 = this.RunFreeze(c.l1.wd, c.l1.ed, c.y1, G1_SIG, G1_CPL);   // g1 NOT b (frozen, couples via plain spur)
    GSController.Sleep(40);
    local r2 = this.RunReader(c.l2.wd, c.l2.ed);                          // g2 AND output
    return [r0, r1, r2];
}

function XorBridgeMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("XB build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    local lastY2 = BASE + 3*BAND + DY_G2;
    this.Prepare(G0_BX - 2, BASE - 2, G2_EAST + 1, lastY2 + 2);

    // four BRIDGE combo copies
    local copies = [];
    for (local k = 0; k < 4; k++) copies.append(this.BuildCopy(BASE + k*BAND, true));
    this.Say("XB built4 b" + (this.allbr ? 1 : 0));

    local combos = [[0,0],[0,1],[1,0],[1,1]];
    local outs = [];
    for (local k = 0; k < 4; k++) {
        local r = this.RunCase(copies[k], combos[k][0], combos[k][1]);
        outs.append(r[2]);
        this.Say("c" + combos[k][0] + combos[k][1] + " " + r[0] + "/" + r[1] + "/" + r[2]);
    }
    // Judge: x > G2_SIG => AND 1. Expected 0,0,0,1.
    local nm = "XB s" + G2_SIG + " " + outs[0] + " " + outs[1] + " " + outs[2] + " " + outs[3] + " b" + (this.allbr ? 1 : 0);
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function XorBridgeMain::Save() { return {}; }
function XorBridgeMain::Load(version, data) {}
