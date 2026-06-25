/*
 * bridgeprobe: prove the BRIDGE CROSSING primitive in isolation, the load-bearing fix for
 * STUCK.md #9 (a signal-free coupling spur SHORTS any flat lane it crosses at grade; a BRIDGE
 * keeps the spur block and the crossed lane block as two separate map tiles).
 *
 * Two independent nets in one copy:
 *   NET A (the COUPLING): a DRIVER train parked above the lane, joined by a pure-vertical
 *     signal-free spur in column SPURX down to a CONSUMER NOT gate's input block. The consumer
 *     reader passes iff the spur did NOT deliver a train, i.e. consumer = NOT(driver bit).
 *   NET B (the CROSSED lane): an independent NOT gate on a horizontal lane at row LY, whose
 *     reader runs west->east. The spur in column SPURX crosses this lane at (SPURX, LY).
 *
 * The crossing of column SPURX with row LY is built as a BRIDGE: a rail bridge spanning
 * (SPURX, LY-1) -> (SPURX, LY+1) OVER the crossed-lane tile (SPURX, LY). In OpenTTD 15.3 the
 * bridge ramp tiles and the tile UNDER the bridge are SEPARATE map tiles in SEPARATE blocks, so
 * the spur's occupancy (driver bit) flows along the bridge into the consumer block WITHOUT
 * merging the crossed lane's block. Both nets then read their true values.
 *
 * CONTROL (level crossing, the failure the bridge fixes): a second copy where the same spur
 * crosses the lane AT GRADE (a level junction, no bridge). The junction merges the spur block
 * and the lane block into ONE block, so a parked driver train OR the crossed reader pollute both.
 *
 * All outputs are RAW reader x (GSMap.GetTileX of the reader train), encoded into the company
 * name. No Squirrel logic decides pass/fail; the operator judges x vs the signal column.
 *
 * Readout: "BP cs<CSIG> ls<LSIG> | brC<x> brL<x> | lvC<x> lvL<x>"  where
 *   brC = bridge-copy CONSUMER reader x  (driver=1 -> spur delivers -> consumer HELD -> x small)
 *   brL = bridge-copy CROSSED  reader x  (its own input absent -> reader PASSES -> x large)
 *   lvC = level-copy  CONSUMER reader x  (control)
 *   lvL = level-copy  CROSSED  reader x  (control)
 * Kept short for the ~31-char company-name limit by emitting two lines in sequence.
 */

// ---- column geometry (absolute), shared by both copies ----
// CROSSED lane B (a NOT of its own input cIn): west depot, reader signal, input tap, term signal.
L_BX   <- 30;            // crossed lane west depot at L_BX-1 (29)
L_SIG  <- L_BX + 6;      // crossed lane reader signal x (36)
L_TIN  <- L_SIG + 1;     // crossed lane input tap x (37)
L_SIGT <- L_SIG + 4;     // crossed lane terminating signal x (40)
L_EAST <- L_SIG + 8;     // crossed lane east depot x (44)

// the spur crosses the crossed lane at SPURX (between the reader signal and the term signal, so
// the crossing sits INSIDE the crossed lane's protected through-block; if it shorts, the merge is
// visible as the crossed reader being held / the consumer reading wrong).
SPURX  <- L_SIG + 2;     // 38  (inside the crossed block L_SIG..L_SIGT)

// CONSUMER lane A (a NOT of the driver bit delivered down the spur): its input block straddles the
// spur's bottom end at SPURX, so a delivered driver train occupies the consumer's input.
C_BX   <- 30;
C_SIG  <- SPURX - 2;     // 36  consumer reader signal; input block C_SIG..C_SIGT straddles SPURX
C_SIGT <- SPURX + 2;     // 40  consumer terminating signal
C_EAST <- SPURX + 6;     // 44  consumer east depot

// DRIVER: a train parked on the spur's TOP end (DRVY) supplies the driver bit (here driver=1).
// The spur runs from DRVY (above the lane) down through LY to CY (the consumer input row).

// Row layout within one copy band:
//   DRVY = gy           driver park row (the spur top)
//   LY   = gy + 3       crossed lane row (the bridge spans over this)
//   CY   = gy + 6       consumer lane row (the spur bottom merges into the consumer block)
DY_DRV <- 0; DY_L <- 3; DY_C <- 6;

BASE <- 30;
BAND <- 14;

class BridgeProbeMain extends GSController {
    company = null; eng = null;
    constructor() {}
}

function BridgeProbeMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
function BridgeProbeMain::Tx(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileX(GSVehicle.GetLocation(v)); }
function BridgeProbeMain::Ty(v) { if (v==null||!GSVehicle.IsValidVehicle(v)) return -1; return GSMap.GetTileY(GSVehicle.GetLocation(v)); }
function BridgeProbeMain::Say(s) { GSCompany.SetName(s); }
function BridgeProbeMain::Prepare(x0, y0, x1, y1) {
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
}

function BridgeProbeMain::SignalVerified(sx, gy) {
    local t = GSMap.GetTileIndex(sx, gy);
    local f = GSMap.GetTileIndex(sx - 1, gy);
    for (local i = 0; i < 8; i++) {
        if (GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE) return true;
        GSRail.BuildSignal(t, f, GSRail.SIGNALTYPE_NORMAL);
        GSController.Sleep(2);
    }
    return GSRail.GetSignalType(t, f) != GSRail.SIGNALTYPE_NONE;
}

// Build a horizontal gate lane (track + 2 depots + reader signal + terminating signal). Returns {wd, ed}.
function BridgeProbeMain::BuildLane(bx, eastx, gy, sigx, sigtx) {
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

// A feeder depot just NORTH of tap tile (tx,gy), joined into the lane.
function BridgeProbeMain::FeederDepot(tx, gy) {
    local d = GSMap.GetTileIndex(tx, gy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, gy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, gy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// Build the DRIVER stub: a depot above DRVY and a single track tile at (SPURX, DRVY) so a parked
// train sits on the spur's top. Returns the depot.
function BridgeProbeMain::DriverStub(drvy) {
    local d = GSMap.GetTileIndex(SPURX, drvy - 1);
    GSRail.BuildRailDepot(d, GSMap.GetTileIndex(SPURX, drvy));
    GSRail.BuildRailTrack(GSMap.GetTileIndex(SPURX, drvy), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(SPURX, drvy), GSRail.RAILTRACK_NW_NE);
    return d;
}

// Build the vertical signal-free coupling spur in column SPURX from drvy down to cy, CROSSING the
// lane at LY. If useBridge, the lane crossing (SPURX, LY) is a BRIDGE spanning (SPURX, LY-1)->(SPURX,
// LY+1) over the lane tile; the lane's own horizontal track stays the tile UNDER the bridge. If not,
// the crossing is a plain level junction (the control: this shorts the spur block into the lane block).
function BridgeProbeMain::BuildSpur(drvy, ly, cy, useBridge) {
    // The bridge spans (SPURX, LY-1) -> (SPURX, LY+1): LY-1 is the head ramp, LY+1 the tail ramp,
    // LY the under-tile (carrying the crossed lane's E-W rail). EMPIRICAL RECIPE (bridgemicro_gs):
    // BuildBridge BUILDS the ramps itself, so the head/tail tiles must NOT have rail pre-laid (laying
    // N-S rail on a ramp tile makes BuildBridge fail). So lay the vertical spur track only on the rows
    // ABOVE the head (drvy..LY-2) and BELOW the tail (LY+2..cy); the bridge connects them over the lane.
    if (useBridge) {
        for (local y = drvy; y <= ly - 2; y++)
            GSRail.BuildRailTrack(GSMap.GetTileIndex(SPURX, y), GSRail.RAILTRACK_NW_SE);
        for (local y = ly + 2; y <= cy; y++)
            GSRail.BuildRailTrack(GSMap.GetTileIndex(SPURX, y), GSRail.RAILTRACK_NW_SE);
        // ensure the under-tile (SPURX, LY) carries the crossed lane's E-W rail before bridging
        // (the empirical recipe: the bridge spans OVER an existing perpendicular rail tile).
        for (local i = 0; i < 8 && !GSRail.IsRailTile(GSMap.GetTileIndex(SPURX, ly)); i++) {
            GSRail.BuildRailTrack(GSMap.GetTileIndex(SPURX, ly), GSRail.RAILTRACK_NE_SW);
            GSController.Sleep(3);
        }
        local head = GSMap.GetTileIndex(SPURX, ly - 1);
        local tail = GSMap.GetTileIndex(SPURX, ly + 1);
        local len = GSMap.DistanceManhattan(head, tail) + 1;
        // verify-and-retry the bridge build (a busy command queue can drop a single BuildBridge).
        for (local i = 0; i < 10; i++) {
            if (GSBridge.IsBridgeTile(head)) break;
            local types = GSBridgeList_Length(len);
            if (!types.IsEmpty())
                GSBridge.BuildBridge(GSVehicle.VT_RAIL, types.Begin(), head, tail);
            GSController.Sleep(4);
        }
        return GSBridge.IsBridgeTile(head);
    } else {
        // level control: continuous vertical spur, crossing tile (SPURX, LY) merges with the lane's
        // horizontal tile as ONE map tile (both tracks, one block) -> the short the bridge fixes.
        for (local y = drvy; y <= cy; y++)
            GSRail.BuildRailTrack(GSMap.GetTileIndex(SPURX, y), GSRail.RAILTRACK_NW_SE);
        return false;
    }
}

// Park a train on tile (tx,gy) from feeder/driver depot d. Freeze it there. Retry BuildVehicle.
function BridgeProbeMain::ParkAt(d, tx, gy, track) {
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

function BridgeProbeMain::BuildReader(wd, ed) {
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

// Run a reader west->east; record where it rests (a HELD reader stops at its red signal, a PASSING
// reader rolls east). Returns final raw x.
function BridgeProbeMain::RunReader(wd, ed) {
    local v = this.BuildReader(wd, ed);
    if (v == null) return -1;
    GSController.Sleep(5);
    for (local r = 0; r < 12; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    // Observe; if it falls back into the depot (a stochastic launch stall), re-nudge it.
    local fx = -1;
    for (local s = 0; s < 40; s++) {
        GSController.Sleep(10);
        if (GSVehicle.IsValidVehicle(v) && GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        local t = this.Tx(v); if (t >= 0) fx = t;
    }
    return fx;
}

// Build one copy (bridge or level). Returns the handles needed to run it.
function BridgeProbeMain::BuildCopy(gy, useBridge) {
    local drvy = gy + DY_DRV, ly = gy + DY_L, cy = gy + DY_C;
    // CONSUMER lane (NET A) on row cy: its input block C_SIG..C_SIGT straddles SPURX.
    local lc = this.BuildLane(C_BX, C_EAST, cy, C_SIG, C_SIGT);
    // CROSSED lane (NET B) on row ly: an independent NOT of cIn, tap at L_TIN.
    local ll = this.BuildLane(L_BX, L_EAST, ly, L_SIG, L_SIGT);
    local lin = this.FeederDepot(L_TIN, ly);
    // DRIVER stub (the spur top).
    local dd = this.DriverStub(drvy);
    // the coupling spur crossing the crossed lane (bridge or level).
    local isBr = this.BuildSpur(drvy, ly, cy, useBridge);
    return { gy = gy, drvy = drvy, ly = ly, cy = cy, lc = lc, ll = ll, lin = lin, dd = dd, isBr = isBr };
}

// Run one copy with driver bit dv and crossed-lane input cv. Returns [consumerX, crossedX, isBridge].
function BridgeProbeMain::RunCopy(c, dv, cv) {
    // park the crossed lane's own input if cv=1 (so the crossed reader is HELD when cv=1, PASSES when cv=0).
    if (cv) this.ParkAt(c.lin, L_TIN, c.ly, true);
    // park the driver train on the spur top if dv=1 (so it occupies the consumer input via the spur).
    if (dv) this.ParkAt(c.dd, SPURX, c.drvy, true);
    GSController.Sleep(10);
    // read the crossed lane (NET B): its reader is independent of the driver IFF isolated.
    local crossedX = this.RunReader(c.ll.wd, c.ll.ed);
    GSController.Sleep(8);
    // read the consumer (NET A): held iff the driver train reached the consumer block through the spur.
    local consumerX = this.RunReader(c.lc.wd, c.lc.ed);
    return [consumerX, crossedX, c.isBr ? 1 : 0];
}

function BridgeProbeMain::Start() {
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID)
        GSController.Sleep(25);
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("BP build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    // four bands: bridge copy with driver=1 cross=0, bridge copy driver=0 cross=1, then two level controls.
    local lastY = BASE + 3*BAND + DY_C;
    this.Prepare(C_BX - 2, BASE - 2, L_EAST + 1, lastY + 2);

    // BRIDGE copies
    local brA = this.BuildCopy(BASE + 0*BAND, true);   // driver=1, cross=0
    local brB = this.BuildCopy(BASE + 1*BAND, true);   // driver=0, cross=1
    // LEVEL controls
    local lvA = this.BuildCopy(BASE + 2*BAND, false);  // driver=1, cross=0
    local lvB = this.BuildCopy(BASE + 3*BAND, false);  // driver=0, cross=1
    this.Say("BP built4 br" + brA.isBr);

    local rbA = this.RunCopy(brA, 1, 0);   // bridge: driver present, crossed input absent
    this.Say("brA c" + rbA[0] + " x" + rbA[1] + " b" + rbA[2]);
    local rbB = this.RunCopy(brB, 0, 1);   // bridge: driver absent, crossed input present
    this.Say("brB c" + rbB[0] + " x" + rbB[1] + " b" + rbB[2]);
    local rlA = this.RunCopy(lvA, 1, 0);   // level control
    this.Say("lvA c" + rlA[0] + " x" + rlA[1]);
    local rlB = this.RunCopy(lvB, 0, 1);

    // Two-phase readout (each kept short). Judge: consumer x > C_SIG => consumer 1; crossed x > L_SIG => crossed 1.
    local n1 = "BP cs" + C_SIG + " ls" + L_SIG + " br " + rbA[0] + " " + rbA[1] + " " + rbB[0] + " " + rbB[1];
    local n2 = "BP lv " + rlA[0] + " " + rlA[1] + " " + rlB[0] + " " + rlB[1] + " isb" + brA.isBr;
    while (true) {
        this.Say(n1); GSController.Sleep(60);
        this.Say(n2); GSController.Sleep(60);
    }
}

function BridgeProbeMain::Save() { return {}; }
function BridgeProbeMain::Load(version, data) {}
