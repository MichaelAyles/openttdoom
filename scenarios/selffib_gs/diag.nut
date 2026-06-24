/*
 * diag: isolate the gate lane. Build ONE 2-input NOR gate lane (the selffib geometry) and run
 * the four NOR cases in sequence on the SAME reused lane, reporting each reader's raw final x via
 * the company name. This pins whether the reused gate lane computes NOR correctly across repeated
 * reads (the selffib full adder reuses one lane for 9 sequential NORs, and NOR(0,0) was returning
 * held=0 instead of pass=1, so the suspect is cross-read block contamination on the reused lane).
 *
 * Expected (GSIGX=46): NOR(0,0) reader passes -> x>46 (out 1); NOR(1,0),NOR(0,1),NOR(1,1) held
 * -> x<=46 (out 0). Readout "DG s46 <x00> <x10> <x01> <x11>". Judge: x>46 => 1.
 * Crucially the cases are run in the order 1,0 / 0,1 / 1,1 / 0,0 / 0,0 so a NOR(0,0) AFTER several
 * tap-parked cases is tested (the failing scenario): the trailing two 0,0 reads MUST pass.
 */
GBX <- 40; GSIGX <- GBX + 6; GTAP0 <- GSIGX + 1; GTAP1 <- GSIGX + 2;
GTERMX <- GSIGX + 4; GEASTX <- GSIGX + 6; GY <- 50;

class DiagMain extends GSController {
    company = null; eng = null;
    wD = null; eD = null; f0 = null; f1 = null;
    constructor() {}
}
function DiagMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function DiagMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function DiagMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function DiagMain::Say(s) { GSCompany.SetName(s); }
function DiagMain::T(x, y) { return GSMap.GetTileIndex(x, y); }
function DiagMain::ClearOrders(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return; while (GSOrder.GetOrderCount(v) > 0) { if (!GSOrder.RemoveOrder(v, 0)) break; } }
function DiagMain::Prepare(x0,y0,x1,y1){ for(local x=x0;x<=x1;x++) for(local y=y0;y<=y1;y++) GSTile.DemolishTile(this.T(x,y)); GSTile.LevelTiles(this.T(x0,y0),this.T(x1,y1)); GSTile.LevelTiles(this.T(x0,y0),this.T(x1,y1)); }

function DiagMain::Build() {
    for (local x = GBX; x < GEASTX; x++) GSRail.BuildRailTrack(this.T(x, GY), GSRail.RAILTRACK_NE_SW);
    this.wD = this.T(GBX - 1, GY); GSRail.BuildRailDepot(this.wD, this.T(GBX, GY));
    this.eD = this.T(GEASTX, GY); GSRail.BuildRailDepot(this.eD, this.T(GEASTX - 1, GY));
    GSRail.BuildSignal(this.T(GSIGX, GY), this.T(GSIGX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(GTERMX, GY), this.T(GTERMX - 1, GY), GSRail.SIGNALTYPE_NORMAL);
    this.f0 = this.T(GTAP0, GY - 1); GSRail.BuildRailDepot(this.f0, this.T(GTAP0, GY)); GSRail.BuildRailTrack(this.T(GTAP0, GY), GSRail.RAILTRACK_NW_NE);
    this.f1 = this.T(GTAP1, GY - 1); GSRail.BuildRailDepot(this.f1, this.T(GTAP1, GY)); GSRail.BuildRailTrack(this.T(GTAP1, GY), GSRail.RAILTRACK_NW_NE);
}
function DiagMain::ParkTap(fD, tx) {
    local v = GSVehicle.BuildVehicle(fD, this.eng);
    if (!GSVehicle.IsValidVehicle(v)) { this.Say("DG park novh"); return null; }
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.T(tx, GY), GSOrder.OF_NON_STOP_INTERMEDIATE);
    for (local r = 0; r < 14; r++) { if (!GSVehicle.IsValidVehicle(v) || !GSVehicle.IsStoppedInDepot(v)) break; GSVehicle.StartStopVehicle(v); GSController.Sleep(10); }
    local tr = "";
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(6);
        local px = this.Tx(v); local py = this.Ty(v);
        if (w < 12) { tr += px + ","; this.Say("DG pk" + tx + " " + tr); }
        if (px==tx && py==GY) { GSVehicle.StartStopVehicle(v); break; }
    }
    if (this.Tx(v)==tx && this.Ty(v)==GY) return v;
    this.Say("DG park FAIL tx" + tx + " at " + this.Tx(v) + "," + this.Ty(v));
    return v;
}
// drive the tap EAST through the lane to the east depot and sell (clean through-path).
function DiagMain::ClearTap(v, fD) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v, this.eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
    local sx = this.Tx(v); local sy = this.Ty(v);
    for (local r = 0; r < 10; r++) { if (!GSVehicle.IsValidVehicle(v)) return; if (!(this.Tx(v)==sx && this.Ty(v)==sy)) break; GSVehicle.StartStopVehicle(v); GSController.Sleep(10); }
    for (local w = 0; w < 36; w++) { GSController.Sleep(10); if (!GSVehicle.IsValidVehicle(v) || GSVehicle.IsStoppedInDepot(v)) break; }
    if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
}
// drain the gate block of any non-essential vehicle (same as selffib pre-read drain).
function DiagMain::Drain() {
    foreach (vv, _ in GSVehicleList()) {
        if (!GSVehicle.IsValidVehicle(vv)) continue;
        local vx = this.Tx(vv); local vy = this.Ty(vv);
        local on = (vy == GY && vx >= GBX - 1 && vx <= GEASTX) || (vy == GY - 1 && (vx == GTAP0 || vx == GTAP1));
        if (!on) continue;
        if (GSVehicle.IsStoppedInDepot(vv)) { GSVehicle.SellVehicle(vv); continue; }
        this.ClearOrders(vv);
        GSOrder.AppendOrder(vv, this.eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsStoppedInDepot(vv)) GSVehicle.StartStopVehicle(vv);
        for (local s = 0; s < 16; s++) { if (!GSVehicle.IsValidVehicle(vv) || GSVehicle.IsStoppedInDepot(vv)) break; GSController.Sleep(8); }
        if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv)) GSVehicle.SellVehicle(vv);
    }
}
function DiagMain::Nor(x, y) {
    this.Drain();
    local p0 = (x==1) ? this.ParkTap(this.f0, GTAP0) : null;
    local p1 = (y==1) ? this.ParkTap(this.f1, GTAP1) : null;
    GSController.Sleep(6);
    local v = GSVehicle.BuildVehicle(this.wD, this.eng);
    local fx = -1;
    if (GSVehicle.IsValidVehicle(v)) {
        GSOrder.AppendOrder(v, this.eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
        // hardened egress: ONE toggle per settle (NudgeEgress discipline), generous budget.
        for (local r = 0; r < 18; r++) { if (!GSVehicle.IsValidVehicle(v)) break; if (!GSVehicle.IsStoppedInDepot(v)) break; GSVehicle.StartStopVehicle(v); GSController.Sleep(10); }
        local trace = "";
        local stable = 0; local lastx = -999; fx = GBX - 1;
        for (local s = 0; s < 20; s++) {
            GSController.Sleep(16); local nx = this.Tx(v); if (nx >= 0) fx = nx;
            if (s < 10) { trace += nx + "."; this.Say("DG mv " + trace); }
            if (GSVehicle.IsStoppedInDepot(v) && fx > GSIGX) break;
            if (fx >= GBX && fx <= GSIGX) { if (fx == lastx) { stable++; if (stable >= 3) break; } else stable = 0; } else stable = 0;
            lastx = fx;
        }
        // dispose: clear taps, DRIVE the reader east to the depot, confirm gone (robust).
        if (p0 != null) { this.ClearTap(p0, this.f0); p0 = null; }
        if (p1 != null) { this.ClearTap(p1, this.f1); p1 = null; }
        this.ClearOrders(v);
        GSOrder.AppendOrder(v, this.eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        for (local s = 0; s < 40; s++) { if (!GSVehicle.IsValidVehicle(v) || GSVehicle.IsStoppedInDepot(v)) break; GSController.Sleep(10); }
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.SellVehicle(v);
    }
    if (p0 != null) this.ClearTap(p0, this.f0);
    if (p1 != null) this.ClearTap(p1, this.f1);
    // confirm lane empty.
    foreach (vv, _ in GSVehicleList()) {
        if (!GSVehicle.IsValidVehicle(vv)) continue;
        if (GSVehicle.IsStoppedInDepot(vv)) { GSVehicle.SellVehicle(vv); continue; }
        local vx = this.Tx(vv); local vy = this.Ty(vv);
        if (vy == GY && vx >= GBX - 1 && vx <= GEASTX) {
            this.ClearOrders(vv); GSOrder.AppendOrder(vv, this.eD, GSOrder.OF_NON_STOP_INTERMEDIATE);
            local px = this.Tx(vv); GSController.Sleep(6);
            if (this.Tx(vv) == px && !GSVehicle.IsStoppedInDepot(vv)) GSVehicle.StartStopVehicle(vv);
            for (local s = 0; s < 30; s++) { if (!GSVehicle.IsValidVehicle(vv) || GSVehicle.IsStoppedInDepot(vv)) break; GSController.Sleep(10); }
            if (GSVehicle.IsValidVehicle(vv) && GSVehicle.IsStoppedInDepot(vv)) GSVehicle.SellVehicle(vv);
        }
    }
    return fx;
}

function DiagMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID) GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("DG build");
    local rt = GSRailTypeList().Begin(); GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);
    for (local w = 0; w < 40 && this.eng == null; w++) { GSController.Sleep(10); this.eng = this.PickEngine(rt); }
    this.Prepare(GBX - 2, GY - 2, GEASTX + 1, GY + 2);
    this.Build();
    this.Say("DG built");
    // Test the EXACT failing case: Nor(0,1) parks the SECOND tap (GTAP1=48), the n1=NOR(a=0,b=1)
    // of FullAdd(0,1,0). Then Nor(1,0) parks the FIRST tap. Then a clean NOR(0,0).
    local x01 = this.Nor(0, 1); this.Say("DG c01 " + x01); GSController.Sleep(20);
    local x10 = this.Nor(1, 0); this.Say("DG c10 " + x10); GSController.Sleep(20);
    local x00 = this.Nor(0, 0); this.Say("DG c00 " + x00); GSController.Sleep(20);
    local nm = "DG s" + GSIGX + " 01=" + x01 + " 10=" + x10 + " 00=" + x00;
    while (true) { this.Say(nm); GSController.Sleep(74); }
}
function DiagMain::Save() { return {}; }
function DiagMain::Load(version, data) {}
