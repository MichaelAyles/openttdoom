/*
 * bridgemicro: isolate the EXACT recipe to build a short N-S rail bridge OVER a perpendicular
 * (E-W) rail tile, reporting success/failure of each variant via the company name. No logic, just
 * "did the bridge build (GSBridge.IsBridgeTile) and the last GSError" per variant.
 *
 * Each variant occupies its own column band so they cannot interfere. A bridge spans (x, y0) ->
 * (x, y2) over the middle tile (x, y1=y0+1). The middle tile carries the E-W "crossed lane" rail.
 *
 * Variant differences (head/tail prep before BuildBridge):
 *   V1: head/tail tiles EMPTY (no track laid), under-tile has E-W rail.
 *   V2: head/tail tiles have N-S rail laid, under-tile has E-W rail.
 *   V3: head/tail tiles EMPTY, under-tile EMPTY.
 *   V4: head/tail tiles EMPTY, under-tile E-W rail, bridge built with length param = distance+1.
 *       (same call as V1 but kept for direct compare of bridge-type pick)
 * Report: "BM v1<0/1>e<err> v2.. v3.. v4.." where the digit is IsBridgeTile(head).
 */

class BridgeMicroMain extends GSController {
    eng = null;
    constructor() {}
}
function BridgeMicroMain::Say(s) { GSCompany.SetName(s); }
function BridgeMicroMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

// Try a bridge spanning (x, y0)->(x, y0+2). headTrack lays N-S rail on the two ramp tiles first.
// underRail lays E-W rail on the middle under-tile first. Returns "<built><err>".
function BridgeMicroMain::TryBridge(x, y0, headTrack, underRail) {
    local y1 = y0 + 1, y2 = y0 + 2;
    if (underRail) GSRail.BuildRailTrack(GSMap.GetTileIndex(x, y1), GSRail.RAILTRACK_NE_SW);
    if (headTrack) {
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, y0), GSRail.RAILTRACK_NW_SE);
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, y2), GSRail.RAILTRACK_NW_SE);
    }
    local head = GSMap.GetTileIndex(x, y0);
    local tail = GSMap.GetTileIndex(x, y2);
    local len = GSMap.DistanceManhattan(head, tail) + 1;   // 3
    local types = GSBridgeList_Length(len);
    local cnt = 0; foreach (t, _ in types) cnt++;
    local ok = false;
    if (!types.IsEmpty())
        ok = GSBridge.BuildBridge(GSVehicle.VT_RAIL, types.Begin(), head, tail);
    local isbr = GSBridge.IsBridgeTile(head) ? 1 : 0;
    return "" + isbr + "ok" + (ok?1:0) + "n" + cnt;
}

function BridgeMicroMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    local mode = GSCompanyMode(GSCompany.COMPANY_FIRST);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("BM build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);

    this.Prepare(28, 28, 60, 50);

    // each variant at its own x column, y0=30
    local v1 = this.TryBridge(32, 30, false, true);
    this.Say("BM v1 " + v1);
    local v2 = this.TryBridge(36, 30, true, true);
    this.Say("BM v2 " + v2);
    local v3 = this.TryBridge(40, 30, false, false);
    this.Say("BM v3 " + v3);
    local v4 = this.TryBridge(44, 34, false, true);   // different y0 to vary
    this.Say("BM v4 " + v4);

    local nm = "BM " + v1 + "|" + v2 + "|" + v3 + "|" + v4;
    while (true) { this.Say(nm); GSController.Sleep(60); }
}
function BridgeMicroMain::Save() { return {}; }
function BridgeMicroMain::Load(version, data) {}
