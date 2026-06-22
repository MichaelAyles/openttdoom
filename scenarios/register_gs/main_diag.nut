/*
 * register diag: isolate how to dispose a reader HELD at a red block signal by an
 * occupied downstream block, WITHOUT disturbing the occupying (HOLD) train. Tries, in
 * sequence, on a held reader, and reports via the company name which method lands the
 * reader in a depot:
 *   M1: ReverseVehicle + order to west depot (the method that failed in main.nut).
 *   M2: lift HOLD into its feeder depot (block clears), let reader roll EAST to the
 *       east depot, sell reader, REBUILD HOLD on its tile (preserves the bit value).
 * Reports "D hx<x> r0<x> m1<x> m2<x>" = HOLD tile x, reader held x, reader x after M1,
 * reader x after M2 (or depot markers 900+).
 */
LX0 <- 30; LX1 <- 38; LY0 <- 20; LY1 <- 26; CDX <- 33;
BX <- 40; RSIGX <- BX + 6; HX <- RSIGX + 1; TSIGX <- RSIGX + 4; EASTX <- RSIGX + 6; GY <- 40;

class DiagMain extends GSController {
    company=null; eng=null; wDepot=null; eDepot=null; holdDepot=null; hold=null; reader=null;
    constructor() {}
}
function DiagMain::PickEngine(rt) {
    foreach (e,_ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e,rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e,_ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function DiagMain::Tx(v){ if(v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function DiagMain::Ty(v){ if(v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function DiagMain::Say(s){ GSCompany.SetName(s); }
function DiagMain::T(x,y){ return GSMap.GetTileIndex(x,y); }
function DiagMain::Prepare(x0,y0,x1,y1){
    for(local x=x0;x<=x1;x++) for(local y=y0;y<=y1;y++) GSTile.DemolishTile(this.T(x,y));
    GSTile.LevelTiles(this.T(x0,y0),this.T(x1,y1)); GSTile.LevelTiles(this.T(x0,y0),this.T(x1,y1));
}
function DiagMain::BuildLane(){
    for(local x=BX;x<EASTX;x++) GSRail.BuildRailTrack(this.T(x,GY),GSRail.RAILTRACK_NE_SW);
    this.wDepot=this.T(BX-1,GY); GSRail.BuildRailDepot(this.wDepot,this.T(BX,GY));
    this.eDepot=this.T(EASTX,GY); GSRail.BuildRailDepot(this.eDepot,this.T(EASTX-1,GY));
    GSRail.BuildSignal(this.T(RSIGX,GY),this.T(RSIGX-1,GY),GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(this.T(TSIGX,GY),this.T(TSIGX-1,GY),GSRail.SIGNALTYPE_NORMAL);
    this.holdDepot=this.T(HX,GY-1); GSRail.BuildRailDepot(this.holdDepot,this.T(HX,GY));
    GSRail.BuildRailTrack(this.T(HX,GY),GSRail.RAILTRACK_NW_NE);
}
function DiagMain::ParkHold(){
    local v=GSVehicle.BuildVehicle(this.holdDepot,this.eng);
    if(!GSVehicle.IsValidVehicle(v)) return;
    GSOrder.AppendOrder(v,this.T(HX,GY),GSOrder.OF_NON_STOP_INTERMEDIATE);
    if(GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for(local w=0;w<50;w++){ GSController.Sleep(5); if(this.Tx(v)==HX&&this.Ty(v)==GY){ GSVehicle.StartStopVehicle(v); break; } }
    this.hold=v;
}
function DiagMain::ClearOrders(v){
    if(v==null||!GSVehicle.IsValidVehicle(v)) return;
    while(GSOrder.GetOrderCount(v)>0){ if(!GSOrder.RemoveOrder(v,0)) break; }
}
function DiagMain::LaunchReader(){
    local v=GSVehicle.BuildVehicle(this.wDepot,this.eng); this.reader=v;
    GSOrder.AppendOrder(v,this.eDepot,GSOrder.OF_NON_STOP_INTERMEDIATE);
    for(local r=0;r<24;r++){ if(GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v); GSController.Sleep(5); if(this.Tx(v)>=BX) break; }
    local fx=BX-1; for(local s=0;s<16;s++){ GSController.Sleep(14); local nx=this.Tx(v); if(nx>=0) fx=nx; }
    return fx;
}
function DiagMain::LiftHold(){
    local v=this.hold; if(v==null||!GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v,this.holdDepot,GSOrder.OF_NON_STOP_INTERMEDIATE);
    if(!GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    GSVehicle.ReverseVehicle(v);
    for(local s=0;s<30;s++){ GSController.Sleep(6); if(GSVehicle.IsStoppedInDepot(v)) break; }
}
function DiagMain::RestoreHold(){
    local v=this.hold; if(v==null||!GSVehicle.IsValidVehicle(v)) return;
    this.ClearOrders(v);
    GSOrder.AppendOrder(v,this.T(HX,GY),GSOrder.OF_NON_STOP_INTERMEDIATE);
    if(GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for(local w=0;w<50;w++){ GSController.Sleep(5); if(this.Tx(v)==HX&&this.Ty(v)==GY){ GSVehicle.StartStopVehicle(v); break; } }
}
// settle marker: if reader stopped in a depot, return 900 + (0 west /1 east); else its x.
function DiagMain::Marker(v){
    if(!GSVehicle.IsValidVehicle(v)) return 800;
    if(GSVehicle.IsStoppedInDepot(v)){
        // which depot? compare to wDepot/eDepot by x
        local x=this.Tx(v);
        return 900+x;
    }
    return this.Tx(v);
}
function DiagMain::Start(){
    while(GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST)==GSCompany.COMPANY_INVALID) GSController.Sleep(25);
    this.company=GSCompany.COMPANY_FIRST; local mode=GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("D build");
    local rt=GSRailTypeList().Begin(); GSRail.SetCurrentRailType(rt); this.eng=this.PickEngine(rt);
    for(local w=0;w<40&&this.eng==null;w++){ GSController.Sleep(10); this.eng=this.PickEngine(rt); }
    GSController.Sleep(20);
    this.Prepare(BX-2,GY-2,EASTX+1,GY+2);
    this.BuildLane();
    this.ParkHold();
    local hx=this.Tx(this.hold);
    // read 1: reader HELD (HOLD occupies the block) at ~RSIGX-1, so r0 ~ 45 (Q=1).
    local r0=this.LaunchReader();
    // dispose via lift+restore: lift HOLD, let reader pass east + sell, restore HOLD.
    this.LiftHold();
    if(GSVehicle.IsValidVehicle(this.reader)){
        if(GSVehicle.IsStoppedInDepot(this.reader)) GSVehicle.StartStopVehicle(this.reader);
        for(local s=0;s<30;s++){ GSController.Sleep(8); if(GSVehicle.IsStoppedInDepot(this.reader)) break; }
        if(GSVehicle.IsValidVehicle(this.reader)&&GSVehicle.IsStoppedInDepot(this.reader)) GSVehicle.SellVehicle(this.reader);
    }
    this.RestoreHold();
    local hx2=this.Tx(this.hold);   // HOLD should be back on HX (47)
    // read 2: HOLD should STILL be there -> reader HELD again -> r1 ~ 45 (Q=1).
    local r1=this.LaunchReader();
    local q1=(r1>RSIGX)?0:((r1>=BX)?1:-1);
    while(true){ this.Say("D hx"+hx+" r0"+r0+" hx2"+hx2+" r1"+r1+" q"+q1); GSController.Sleep(60); }
}
function DiagMain::Save(){ return {}; }
function DiagMain::Load(v,d){}
