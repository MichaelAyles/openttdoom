/*
 * clockgate: a CLOCK train on a closed rail loop, the periodic edge the whole
 * synchronous design needs. Sub-goal 1 of the clocked-gate de-risk.
 *
 * A single train runs a small rectangular loop forever. Once per lap it passes a
 * fixed reference point, which is the clock edge. To PROVE the period is real and
 * stable (not the train stuck, not a one-off), we sample the train's tile (x,y) at
 * fixed wall-clock intervals across several laps and encode a run of successive
 * samples into the COMPANY NAME, read back with "rcon companies". An external judge
 * sees the position sweep around the loop and the same positions recur with a
 * repeating period.
 *
 * LOOP GEOMETRY (rectangle, corners are single curve pieces).
 * OpenTTD edges: +X is the SW edge, -X the NE edge, +Y the SE edge, -Y the NW edge.
 *   top run    Y=LY0, X in [LX0..LX1] : straight NE_SW
 *   bottom run Y=LY1, X in [LX0..LX1] : straight NE_SW
 *   left run   X=LX0, Y in [LY0..LY1] : straight NW_SE
 *   right run  X=LX1, Y in [LY0..LY1] : straight NW_SE
 *   corner (LX0,LY0) top-left     : SW_SE  (top continues +X, left continues +Y)
 *   corner (LX1,LY0) top-right    : NE_SE  (top arrives -X, right continues +Y)
 *   corner (LX1,LY1) bottom-right : NW_NE  (bottom continues -X, right arrives -Y)
 *   corner (LX0,LY1) bottom-left  : NW_SW  (bottom arrives +X, left arrives -Y)
 * These corner constants match the known-working norchain coupling spur.
 *
 * A depot is dropped onto the top run so we can spawn the train onto the loop. The
 * train gets TWO destination orders, to the bottom-right corner and the top-left
 * corner, so its order list cycles and it circles the ring forever (an order list
 * repeats once the last order is reached).
 */

// Loop rectangle. Kept small so a lap is a handful of seconds at default speed.
LX0 <- 30;
LX1 <- 38;
LY0 <- 30;
LY1 <- 36;
// depot sits just north of the top run, feeding tile (DX, LY0).
DX  <- 33;

class ClockGateMain extends GSController {
    company = null; eng = null;
    clock = null;
    depot = null;
    constructor() {}
}

function ClockGateMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function ClockGateMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function ClockGateMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function ClockGateMain::Say(s) { GSCompany.SetName(s); }

function ClockGateMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

function ClockGateMain::T(x, y) { return GSMap.GetTileIndex(x, y); }

// Build the closed rectangular loop. Returns the count of successful track builds.
function ClockGateMain::BuildLoop() {
    local n = 0;
    // top + bottom straight runs (interior tiles only; corners get curves).
    for (local x = LX0 + 1; x < LX1; x++) {
        if (GSRail.BuildRailTrack(this.T(x, LY0), GSRail.RAILTRACK_NE_SW)) n++;
        if (GSRail.BuildRailTrack(this.T(x, LY1), GSRail.RAILTRACK_NE_SW)) n++;
    }
    // left + right straight runs (interior tiles only).
    for (local y = LY0 + 1; y < LY1; y++) {
        if (GSRail.BuildRailTrack(this.T(LX0, y), GSRail.RAILTRACK_NW_SE)) n++;
        if (GSRail.BuildRailTrack(this.T(LX1, y), GSRail.RAILTRACK_NW_SE)) n++;
    }
    // four corner curves.
    if (GSRail.BuildRailTrack(this.T(LX0, LY0), GSRail.RAILTRACK_SW_SE)) n++;  // top-left
    if (GSRail.BuildRailTrack(this.T(LX1, LY0), GSRail.RAILTRACK_NE_SE)) n++;  // top-right
    if (GSRail.BuildRailTrack(this.T(LX1, LY1), GSRail.RAILTRACK_NW_NE)) n++;  // bottom-right
    if (GSRail.BuildRailTrack(this.T(LX0, LY1), GSRail.RAILTRACK_NW_SW)) n++;  // bottom-left
    return n;
}

function ClockGateMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("CLK build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    this.Prepare(LX0 - 2, LY0 - 2, LX1 + 2, LY1 + 2);

    local built = this.BuildLoop();

    // Depot just north of the top run at (DX, LY0-1), connecting into (DX, LY0).
    // The top run tile (DX,LY0) needs the depot spur joined: it already has the
    // straight NE_SW; add the NW_NE corner so the depot (to its north) connects.
    this.depot = this.T(DX, LY0 - 1);
    local dok = GSRail.BuildRailDepot(this.depot, this.T(DX, LY0));
    // join the depot exit into the loop: a curve on (DX,LY0) toward the depot (-Y, NW).
    // the loop straight there is NE_SW; add NW_NE (joins NW edge to NE edge) and
    // NW_SW so a train can leave the depot and turn onto the ring either way.
    GSRail.BuildRailTrack(this.T(DX, LY0), GSRail.RAILTRACK_NW_NE);
    GSRail.BuildRailTrack(this.T(DX, LY0), GSRail.RAILTRACK_NW_SW);

    this.Say("CLK b" + built + " d" + (dok ? 1 : 0));

    // Spawn the clock train and send it round the loop with two cycling orders.
    this.clock = GSVehicle.BuildVehicle(this.depot, this.eng);
    if (!GSVehicle.IsValidVehicle(this.clock)) { this.Say("CLK NOVEH"); while (true) GSController.Sleep(74); }
    // Two destination tiles on opposite sides of the ring. The order list repeats,
    // so the train circles forever: go to bottom-right, then to top-left, repeat.
    GSOrder.AppendOrder(this.clock, this.T(LX1, LY1), GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSOrder.AppendOrder(this.clock, this.T(LX0, LY0), GSOrder.OF_NON_STOP_INTERMEDIATE);
    // release it from the depot.
    for (local r = 0; r < 10; r++) {
        if (GSVehicle.IsStoppedInDepot(this.clock)) GSVehicle.StartStopVehicle(this.clock);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(this.clock)) break;
    }
    this.Say("CLK rolling");

    // Sample the train tile (x,y) at fixed wall-clock intervals and stream a run of
    // successive samples into the company name so a judge sees the position cycle.
    // Encode as "CK x0.y0 x1.y1 x2.y2 x3.y3" four samples per name, then advance.
    // We keep a rolling window and also a small history to prove the period.
    // rolling window of the last few (x,y) samples kept as four plain locals, so
    // there is no array allocation per iteration (a defensive simplification).
    local s0 = ""; local s1 = ""; local s2 = ""; local s3 = "";
    local idx = 0;
    while (true) {
        GSController.Sleep(20);           // fixed interval between samples
        local cx = this.Tx(this.clock);
        local cy = this.Ty(this.clock);
        s0 = s1; s1 = s2; s2 = s3; s3 = cx + "." + cy;
        this.Say("CK" + idx + " " + s0 + " " + s1 + " " + s2 + " " + s3);
        idx++;
    }
}

function ClockGateMain::Save() { return {}; }
function ClockGateMain::Load(version, data) {}
