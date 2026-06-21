/*
 * computecell: the FUSION milestone. The toolchain (synth -> place -> route -> emit)
 * produces a placement (scenario_data.nut, GetScenarioData()), and THIS GameScript
 * reads that placement and STAMPS a real computing NOR cell at the placed position,
 * then proves it computes by running readers over the four input combinations and
 * reading the RAW reader x of where each stops.
 *
 * The gate primitive is the VERIFIED norgate_gs construction (a block-signal NOR),
 * lifted verbatim and parameterised at the placed (cx, cy) with a variable number of
 * input taps (1 tap = NOT, 2 taps = NOR2). NOTHING is hand-coded to fixed map
 * coordinates: the cell origin and the tap/output pin tiles all come from the emitted
 * placement, which is the whole point of the milestone.
 *
 * Cell footprint, anchored on the placed origin (cell.x, cell.y), n = number of inputs:
 *   lane row Y = cell.y + 1            (cell.y is the feeder-depot row, just north)
 *   BX  = cell.x + 1                   first track tile, west depot at cell.x = BX-1
 *   SIGX = BX + 6                      reader (eastbound-permissive) signal
 *   taps = SIGX+1 .. SIGX+n            one input tap per input pin
 *   SIG2X = SIGX + n + 2               terminating signal (keeps the input block a
 *                                      through block, so a present train holds the reader)
 *   EASTX = SIG2X + 2                  east depot; reader rests here (x = EASTX) iff it passed
 *
 * A bit is a train present/absent on an input tap. A normal block signal is RED iff its
 * protected block is occupied, so the reader passes SIGX iff EVERY tap is empty = NOR.
 * The output is read from where the reader stops: x > SIGX means it passed (output 1).
 * BuildSignal(tile, front) permits travel FROM front INTO tile, so the eastbound reader
 * signal needs front = SIGX-1 (the opposite of the naive guess).
 *
 * Readout: the four raw reader x are encoded SHORT into the COMPANY NAME (the ~31-char
 * limit silently freezes long names), read back via "rcon companies". The bit for each
 * combo is judged externally from x > SIGX, NOT computed in Squirrel from the inputs.
 */

require("scenario_data.nut");   // GetScenarioData(), emitted by place_and_route

class ComputeCellMain extends GSController {
    data = null; company = null; eng = null;
    constructor() {}
}

function ComputeCellMain::PickEngine(rt) {
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL))
        if (GSEngine.IsBuildable(e) && GSEngine.CanRunOnRail(e, rt) && !GSEngine.IsWagon(e)) return e;
    foreach (e, _ in GSEngineList(GSVehicle.VT_RAIL)) if (GSEngine.IsBuildable(e)) return e;
    return null;
}
// Build a reader/feeder in `depot`, retrying until the handle is valid (a transient build
// failure on a fresh server returns an invalid vehicle, the observed -1 launch flake), give it
// its order, then dispatch it and CONFIRM it actually leaves the depot. The observed whole-run
// "all readers stuck at their west depot" stall (readout OR s24 17 17 17 17) is exactly a reader
// that built but never left the depot: StartStopVehicle can be dropped while a build-command
// backlog is draining on a fresh/contended server. So we nudge it out over a long window and
// re-append the order if it ever got lost. Returns the (valid) vehicle handle, or null.
function ComputeCellMain::BuildAndLaunch(depot, dest) {
    local depx = GSMap.GetTileX(depot), depy = GSMap.GetTileY(depot);
    // Build ONE train, retrying only the (rare) transient invalid handle. We deliberately keep
    // command volume low: a storm of BuildVehicle/SellVehicle retries trips the GS command-rate
    // limit and throttles the whole script, which itself looks like a stall. So the primary
    // strategy is to be PATIENT with a single train, nudging it out over a long window, and only
    // sell+rebuild ONCE as a genuine last resort.
    local v = null;
    for (local b = 0; b < 5; b++) {
        v = GSVehicle.BuildVehicle(depot, this.eng);
        if (GSVehicle.IsValidVehicle(v)) break;
        GSController.Sleep(10);
    }
    if (!GSVehicle.IsValidVehicle(v)) return null;
    GSOrder.AppendOrder(v, dest, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(6);

    // Helper-free inline nudge loop: re-issue Start only while genuinely stopped in the depot
    // (re-appending a lost order), and CONFIRM the train has advanced off the depot tile (its
    // location is no longer the depot tile). Returns true once it has launched onto the lane.
    local launched = false;
    for (local r = 0; r < 50; r++) {
        if (!GSVehicle.IsValidVehicle(v)) break;
        if (GSVehicle.IsStoppedInDepot(v)) {
            if (GSOrder.GetOrderCount(v) == 0)
                GSOrder.AppendOrder(v, dest, GSOrder.OF_NON_STOP_INTERMEDIATE);
            GSVehicle.StartStopVehicle(v);
            GSController.Sleep(7);   // give the start command time to take before re-toggling
        } else {
            local loc = GSVehicle.GetLocation(v);
            if (GSMap.GetTileX(loc) != depx || GSMap.GetTileY(loc) != depy) { launched = true; break; }
            GSController.Sleep(5);
        }
    }
    if (launched) return v;

    // Genuine last resort: the train never left the depot in the whole window. Sell it and try
    // ONE clean rebuild (a single retry keeps command volume bounded).
    if (GSVehicle.IsValidVehicle(v)) GSVehicle.SellVehicle(v);
    GSController.Sleep(10);
    v = null;
    for (local b = 0; b < 5; b++) {
        v = GSVehicle.BuildVehicle(depot, this.eng);
        if (GSVehicle.IsValidVehicle(v)) break;
        GSController.Sleep(10);
    }
    if (!GSVehicle.IsValidVehicle(v)) return null;
    GSOrder.AppendOrder(v, dest, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(6);
    for (local r = 0; r < 50; r++) {
        if (!GSVehicle.IsValidVehicle(v)) break;
        if (GSVehicle.IsStoppedInDepot(v)) {
            if (GSOrder.GetOrderCount(v) == 0)
                GSOrder.AppendOrder(v, dest, GSOrder.OF_NON_STOP_INTERMEDIATE);
            GSVehicle.StartStopVehicle(v);
            GSController.Sleep(7);
        } else {
            local loc = GSVehicle.GetLocation(v);
            if (GSMap.GetTileX(loc) != depx || GSMap.GetTileY(loc) != depy) return v;
            GSController.Sleep(5);
        }
    }
    return v;   // return the (valid) handle even if egress was not confirmed; caller polls position
}
function ComputeCellMain::Tx(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return -1;
    return GSMap.GetTileX(GSVehicle.GetLocation(v));
}
function ComputeCellMain::Ty(v) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return -1;
    return GSMap.GetTileY(GSVehicle.GetLocation(v));
}
function ComputeCellMain::Say(s) { GSCompany.SetName(s); }

function ComputeCellMain::Prepare(x0, y0, x1, y1) {
    // Demolishing the whole band-box is hundreds to ~a thousand DoCommands. Issuing them in a
    // tight loop with no yield floods the GS command queue, and later reader-launch commands then
    // sit behind that backlog (the observed "reader barely left the depot / -1 launch" failures
    // happen when the queue is still draining). Yield periodically so the queue stays shallow.
    local issued = 0;
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++) {
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
            if ((++issued % 24) == 0) GSController.Sleep(2);
        }
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSController.Sleep(4);
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSController.Sleep(8);
}

/*
 * Derive the gate geometry of a placed cell purely from its origin (cell.x, cell.y)
 * and its input count. Returns a table of tile-x coordinates and the lane row Y, plus
 * the feeder-depot row. This is the parameterised stamp's coordinate model; the actual
 * track is laid by StampCell from these numbers. Keeping derivation separate lets the
 * sweep reuse the exact same SIGX/EASTX/tap tiles the build used.
 */
function ComputeCellMain::Geom(cell) { return this.GeomAt(cell, 0); }

// Geom with a vertical row offset `dy`, so Stage 2 can stamp independent per-combo copies
// of the same placed cells at their own row bands (the norchain "no teardown" lesson). All x
// come straight from cell.x; only the row shifts. dy=0 is the placement's own position.
function ComputeCellMain::GeomAt(cell, dy) {
    local n = cell.inputs.len();
    if (n < 1) n = 1;            // a 0-input buildable would be CONST; this path is NOR/NOT
    local bx    = cell.x + 1;
    local sigx  = bx + 6;
    local sig2x = sigx + n + 2;
    local eastx = sig2x + 2;
    local taps = [];
    for (local i = 0; i < n; i++) taps.append(sigx + 1 + i);
    return {
        n = n, Y = cell.y + 1 + dy, fy = cell.y + dy,
        bx = bx, sigx = sigx, sig2x = sig2x, eastx = eastx, taps = taps,
        wdepot_x = cell.x
    };
}

/*
 * Stamp ONE computing NOR/NOT cell from the placement. Builds the verified geometry
 * relative to (cell.x, cell.y): west depot, eastbound track lane, reader signal with
 * front = SIGX-1, n input taps each with a feeder depot just north, a terminating
 * signal, and an east depot. Returns the Geom table so the caller can drive it.
 *
 * No coordinate here is a fixed map address: every tile is cell.x/cell.y plus a fixed
 * footprint offset, so moving the cell in the placement moves the whole gate.
 */
function ComputeCellMain::StampCell(cell) { return this.StampGeom(cell, this.Geom(cell), true); }

// Build the gate described by `g` (a Geom/GeomAt table for `cell`). `eastDepot` controls
// whether the east depot is built: SC1 and gate2 build it (the reader rests there on pass);
// Stage 2's gate1 omits it so its passing reader continues east onto the coupling lane into
// gate2's input block. Returns g, augmented with the built depot/feeder tile indices.
function ComputeCellMain::StampGeom(cell, g, eastDepot) {
    GSLog.Info("  stamp " + cell.type + " '" + cell.id + "' at (" + cell.x + "," + cell.y
               + ") row=" + g.Y + " n=" + g.n + " sigx=" + g.sigx + " taps0=" + g.taps[0]
               + " eastx=" + g.eastx + " eastDepot=" + eastDepot);

    // east-west track lane.
    for (local x = g.bx; x < g.eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, g.Y), GSRail.RAILTRACK_NE_SW);
    // west depot (reader spawns here).
    g.wdepot <- GSMap.GetTileIndex(g.wdepot_x, g.Y);
    GSRail.BuildRailDepot(g.wdepot, GSMap.GetTileIndex(g.bx, g.Y));
    if (eastDepot) {
        g.edepot <- GSMap.GetTileIndex(g.eastx, g.Y);
        GSRail.BuildRailDepot(g.edepot, GSMap.GetTileIndex(g.eastx - 1, g.Y));
    } else {
        g.edepot <- null;
    }
    // eastbound-permissive reader signal (front = SIGX-1) + terminating signal.
    GSRail.BuildSignal(GSMap.GetTileIndex(g.sigx,  g.Y), GSMap.GetTileIndex(g.sigx - 1,  g.Y), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(g.sig2x, g.Y), GSMap.GetTileIndex(g.sig2x - 1, g.Y), GSRail.SIGNALTYPE_NORMAL);
    // one input tap per input, each fed from a depot just north so a train can be parked on it.
    g.inDepots <- [];
    for (local i = 0; i < g.n; i++) {
        local tx = g.taps[i];
        local d = GSMap.GetTileIndex(tx, g.fy);
        GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, g.Y));
        GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, g.Y), GSRail.RAILTRACK_NW_NE);
        g.inDepots.append(d);
    }
    return g;
}

// Park an input train on tile (tx, Y) from its feeder depot, stopping it dead on the tap.
// Returns the vehicle handle; the caller verifies it is CONFIRMED on the tap with OnTap().
function ComputeCellMain::ParkInput(inDepot, tx, Y) {
    local v = null;
    // The build itself can flake (transient invalid handle on a fresh server), so retry it a
    // few times. Keep command volume modest to avoid tripping the GS command-rate throttle.
    for (local b = 0; b < 5; b++) {
        v = GSVehicle.BuildVehicle(inDepot, this.eng);
        if (GSVehicle.IsValidVehicle(v)) break;
        GSController.Sleep(10);
    }
    if (!GSVehicle.IsValidVehicle(v)) return null;
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
    // Get it moving out of the depot first (re-issue Start while stopped in the depot).
    for (local w = 0; w < 30; w++) {
        if (!GSVehicle.IsValidVehicle(v)) return null;
        if (GSVehicle.IsStoppedInDepot(v)) {
            if (GSOrder.GetOrderCount(v) == 0)
                GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
            GSVehicle.StartStopVehicle(v);
            GSController.Sleep(7);
        } else {
            break;   // on the lane now
        }
    }
    // CATCH the train ON the tap and freeze it dead. The tap tile is a lane junction and the order
    // is non-stop, so the train will NOT stop there on its own, it sails onto the east-west lane.
    // We must poll FAST so we do not overshoot the single tap tile: a coarse poll can sample the
    // train one tile before and one tile after the tap, never catching it, which leaves the input
    // ABSENT and makes gate1 wrongly pass (the 0,0,1,1 failure). Tight poll = reliable freeze. If
    // it overshoots east of the tap, we give up on this train (return it off-tap) and the caller
    // (ParkInputConfirmed) detects not-OnTap and rebuilds a fresh one.
    for (local w = 0; w < 120; w++) {
        if (!GSVehicle.IsValidVehicle(v)) return null;
        local loc = GSVehicle.GetLocation(v);
        local vx = GSMap.GetTileX(loc), vy = GSMap.GetTileY(loc);
        if (vx == tx && vy == Y) {
            GSVehicle.StartStopVehicle(v);   // dead stop on the tap
            break;
        }
        if (vx > tx && vy == Y) break;   // overshot onto the lane: unrecoverable, let caller rebuild
        GSController.Sleep(2);
    }
    return v;
}

// True iff vehicle v is valid and currently sitting on tile (tx, Y).
function ComputeCellMain::OnTap(v, tx, Y) {
    if (v == null || !GSVehicle.IsValidVehicle(v)) return false;
    local loc = GSVehicle.GetLocation(v);
    return GSMap.GetTileX(loc) == tx && GSMap.GetTileY(loc) == Y;
}

// Park an input train and CONFIRM it ends up STABLY resting on its exact tap tile, retrying
// the whole placement (sell + rebuild) up to a few attempts. "Stable" = on the tap across two
// consecutive polls (so we know it has stopped dead, not just passing through). Returns the
// parked vehicle, or null if it could never be confirmed (the caller must not read a gate
// with an unconfirmed input).
function ComputeCellMain::ParkInputConfirmed(inDepot, tx, Y) {
    local v = null;
    for (local attempt = 0; attempt < 3; attempt++) {
        v = this.ParkInput(inDepot, tx, Y);
        // poll for the train to be resting on the tap tile across two consecutive checks.
        local stable = 0;
        for (local w = 0; w < 24; w++) {
            if (this.OnTap(v, tx, Y)) {
                stable++;
                if (stable >= 2) return v;   // confirmed parked and stationary on the tap
            } else {
                stable = 0;
            }
            GSController.Sleep(5);
        }
        // not confirmed: tear this attempt down and rebuild fresh.
        if (v != null && GSVehicle.IsValidVehicle(v)) GSVehicle.SellVehicle(v);
        GSController.Sleep(8);
    }
    return null;
}

// Run a fresh reader west->east on gate g, return its final x (>SIGX means it passed).
function ComputeCellMain::RunReader(g) {
    local v = GSVehicle.BuildVehicle(g.wdepot, this.eng);
    GSOrder.AppendOrder(v, g.edepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v)) break;
    }
    local fx = g.bx - 1;
    for (local s = 0; s < 16; s++) { GSController.Sleep(18); fx = this.Tx(v); }
    return { fx = fx, v = v };
}

/*
 * One truth-table row on gate g: set inputs per the bit-vector `bits` (LSB = input 0),
 * run a fresh reader, record its RAW final x, then tear the inputs and reader down so
 * the next combo runs on a clean gate. Returns the raw reader x (NOT a computed bit).
 */
function ComputeCellMain::Case(g, bits) {
    local ins = [];
    for (local i = 0; i < g.n; i++) {
        if (bits & (1 << i)) ins.append(this.ParkInput(g.inDepots[i], g.taps[i], g.Y));
        else                 ins.append(null);
    }
    GSController.Sleep(10);
    local rr = this.RunReader(g);
    // teardown: sell the input trains, let the (possibly held) reader roll into the east
    // depot once the block clears, then sell it. Leaves the gate empty for the next combo.
    foreach (v in ins) if (v != null && GSVehicle.IsValidVehicle(v)) GSVehicle.SellVehicle(v);
    for (local s = 0; s < 16; s++) {
        GSController.Sleep(12);
        if (GSVehicle.IsStoppedInDepot(rr.v)) break;
    }
    if (GSVehicle.IsValidVehicle(rr.v)) GSVehicle.SellVehicle(rr.v);
    GSController.Sleep(10);
    return rr.fx;
}

/*
 * ---- STAGE 2: a 2-cell OR = NOT(NOR(a,b)) with the inter-cell bit on a routed net ----
 *
 * gate1 (cell0) is a NOR2(a,b); gate2 (cell1) is a NOT whose single input net == gate1's
 * output net. The emitted placement gives both origins and the route `w` connecting
 * gate1.output -> gate2.input, which is what tells us the two couple (we verify the route
 * exists, we do not hardcode the link). The bit travels on that coupling: gate1's reader,
 * when it PASSES (output 1, inputs absent), runs east along its lane to a coupling tile CPLX
 * and freezes there; a vertical no-signal spur joins CPLX into gate2's input block, so a
 * passing gate1 OCCUPIES gate2's input block. gate2's reader then passes iff its block is
 * empty iff gate1 did NOT pass, giving gate2 = NOT(gate1) = OR(a,b).
 *
 * CPLX is a tile of gate2's input block (between gate2's reader signal and its terminating
 * signal), read from gate2's placed geometry, so the coupling point is placement-derived.
 * As in norchain, each of the 4 combos is an INDEPENDENT copy at its own row band (freezing
 * a reader on a coupled junction is fragile to tear down), so cases cannot pollute each other.
 */

// Build one independent OR-chain copy for input combo `bits`, at row band offset `dy`.
// g0cell/g1cell are the placed NOR2 and NOT cells. Returns [g1x, g2x] raw reader x.
//
// COUPLING = fix path (A), the placement-constrained chain layout that reproduces the
// VERIFIED norchain geometry from the emitted placement. norchain only merged the two
// signal blocks because gate2's input block OVERLAPPED gate1's frozen rest tile via a
// SHORT PURE-VERTICAL signal-free spur (no horizontal run). The toolchain places gate2
// ~17 tiles east of gate1, which turned the spur into a long L that does NOT merge in
// 15.3 (the documented blocker). So here the consumer cell is CO-LOCATED relative to its
// driver: gate2 is stamped 3 rows below gate1 with its x chosen so its input TAP lands in
// exactly the column of gate1's frozen rest tile (grest), and the coupling is a 3-row pure
// vertical spur at x=grest, identical to the proven norchain spur. Every coordinate is
// derived from the PLACED gate1 origin (g0cell.x/.y), so moving gate1 in the placement
// moves the whole chain. This is the chain placement constraint applied at stamp time.
function ComputeCellMain::RunCopyOR(g0cell, g1cell, dy, bits) {
    // gate1 = NOR2 at its placed origin (band-shifted). Lane row g1.Y, taps, signals as usual.
    local g1 = this.GeomAt(g0cell, dy);          // gate1 = NOR2
    // GREST: gate1's reader natural REST tile when it passes. A passing reader coasts ~2 tiles
    // past the terminating signal and stops (the norchain "held a tile early" behaviour), so its
    // output train always rests just east of gate1's terminating signal. Derived from gate1's geom.
    local grest = g1.sig2x + 2;

    // gate2 = NOT, CO-LOCATED 3 rows below gate1 so its input TAP column == grest. With the
    // gate Geom (bx=cx+1, sigx=bx+6, first tap=sigx+1), tap == cx+8, so cx2 = grest-8 lands the
    // tap exactly on gate1's rest column. The whole gate2 geometry is then derived from gate1.
    local g2bx   = grest - 7;          // = cx2 + 1
    local g2sigx = g2bx + 6;           // gate2 reader signal x (= grest - 1)
    local g2tap  = g2sigx + 1;         // gate2 input tap x (== grest)
    local g2sig2x = g2sigx + 1 + 2;    // gate2 terminating signal (n=1)
    local g2eastx = g2sig2x + 2;       // gate2 east depot (reader rests here on pass)
    local g2Y    = g1.Y + 3;           // gate2 lane row, three below gate1 (norchain gy2=gy1+3)
    // INVARIANT: g2tap == grest, so gate1's frozen rest tile and gate2's input tap share a column
    // and the coupling is a pure-vertical spur (the only construction that merges the blocks in 15.3).

    // ---- gate1: lane bx..g1eastx, west depot, east depot FAR past grest so the reader is on
    // OPEN TRACK (in the block) when frozen at grest, exactly like norchain (depot at CPLX+4).
    // A near depot lets the passing reader roll into the depot (removed from the block) before
    // the freeze catches it, so the merge would read empty. grest+5 keeps it clearly on track.
    local g1eastx = grest + 5;
    for (local x = g1.bx; x <= g1eastx - 1; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, g1.Y), GSRail.RAILTRACK_NE_SW);
    g1.wdepot <- GSMap.GetTileIndex(g1.wdepot_x, g1.Y);
    GSRail.BuildRailDepot(g1.wdepot, GSMap.GetTileIndex(g1.bx, g1.Y));
    local g1eDepot = GSMap.GetTileIndex(g1eastx, g1.Y);
    GSRail.BuildRailDepot(g1eDepot, GSMap.GetTileIndex(g1eastx - 1, g1.Y));
    GSRail.BuildSignal(GSMap.GetTileIndex(g1.sigx,  g1.Y), GSMap.GetTileIndex(g1.sigx - 1,  g1.Y), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(g1.sig2x, g1.Y), GSMap.GetTileIndex(g1.sig2x - 1, g1.Y), GSRail.SIGNALTYPE_NORMAL);
    g1.inDepots <- [];
    for (local i = 0; i < g1.n; i++) {
        local tx = g1.taps[i];
        local d = GSMap.GetTileIndex(tx, g1.fy);
        GSRail.BuildRailDepot(d, GSMap.GetTileIndex(tx, g1.Y));
        GSRail.BuildRailTrack(GSMap.GetTileIndex(tx, g1.Y), GSRail.RAILTRACK_NW_NE);
        g1.inDepots.append(d);
    }

    // ---- gate2: NOT lane on row g2Y, co-located so its tap (g2tap) sits at x=grest. Built by
    // hand (not StampGeom) so the geometry is the norchain-faithful one derived above.
    for (local x = g2bx; x < g2eastx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, g2Y), GSRail.RAILTRACK_NE_SW);
    local g2wDepot = GSMap.GetTileIndex(g2bx - 1, g2Y);
    GSRail.BuildRailDepot(g2wDepot, GSMap.GetTileIndex(g2bx, g2Y));
    local g2eDepot = GSMap.GetTileIndex(g2eastx, g2Y);
    GSRail.BuildRailDepot(g2eDepot, GSMap.GetTileIndex(g2eastx - 1, g2Y));
    GSRail.BuildSignal(GSMap.GetTileIndex(g2sigx,  g2Y), GSMap.GetTileIndex(g2sigx - 1,  g2Y), GSRail.SIGNALTYPE_NORMAL);
    GSRail.BuildSignal(GSMap.GetTileIndex(g2sig2x, g2Y), GSMap.GetTileIndex(g2sig2x - 1, g2Y), GSRail.SIGNALTYPE_NORMAL);
    // gate2 takes its only input from the inter-cell spur, NOT from a parked train, so its tap tile
    // (g2tap == grest) gets no feeder depot: it stays a plain lane tile that the vertical spur joins
    // from the north, keeping that column clear for the pure-vertical coupling.

    // ---- COUPLING: the emitted routed net gate1.output -> gate2.input, realised as the proven
    // norchain SHORT PURE-VERTICAL spur (NO signals) at x=grest from gate1's lane down to gate2's
    // lane, so gate1's output block and gate2's input block become ONE block. Identical to
    // norchain BuildCopy's spur (the only construction that merged the blocks in 15.3).
    //   (grest, g1.Y): lane piece (NE_SW) already there; add SW_SE so it also turns down (south).
    //   (grest, mid):  pure vertical NW_SE.
    //   (grest, g2Y):  lane piece (NE_SW) already there; add NW_NE so it joins from the north.
    GSRail.BuildRailTrack(GSMap.GetTileIndex(grest, g1.Y), GSRail.RAILTRACK_SW_SE);
    for (local y = g1.Y + 1; y < g2Y; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(grest, y), GSRail.RAILTRACK_NW_SE);
    GSRail.BuildRailTrack(GSMap.GetTileIndex(grest, g2Y), GSRail.RAILTRACK_NW_NE);

    // Let the build/terraform command backlog drain before running any reader. Reader dispatch
    // issued on top of a still-draining build queue is the all-readers-stuck-in-depot / barely-
    // moved stall, so we settle generously here before parking inputs or launching readers.
    GSController.Sleep(25);

    // Pre-park gate1's primary inputs a,b per the combo, and CONFIRM each one is actually
    // resting on its tap before the reader runs. An input that fails to park would make gate1
    // wrongly see an empty block and pass (the observed 0,0,1,1 case-01 failure). We hold the
    // parked handles and do not proceed to read the gate until every required input is confirmed
    // on its tap; if any slipped while the others parked, we re-park it.
    local needInputs = [];
    for (local i = 0; i < g1.n; i++)
        if (bits & (1 << i)) needInputs.append(i);
    local parked = {};
    foreach (i in needInputs)
        parked[i] <- this.ParkInputConfirmed(g1.inDepots[i], g1.taps[i], g1.Y);
    // Final strict gate: every required input must be on its exact tap RIGHT NOW. Re-park any
    // that drifted, a few times, before launching the reader.
    for (local pass = 0; pass < 3; pass++) {
        local allOn = true;
        foreach (i in needInputs) {
            if (!this.OnTap(parked[i], g1.taps[i], g1.Y)) {
                allOn = false;
                if (parked[i] != null && GSVehicle.IsValidVehicle(parked[i]))
                    GSVehicle.SellVehicle(parked[i]);
                parked[i] = this.ParkInputConfirmed(g1.inDepots[i], g1.taps[i], g1.Y);
            }
        }
        if (allOn) break;
    }
    GSController.Sleep(8);

    // Run gate1's reader toward its east depot; it coasts to grest and rests there iff it passes
    // (inputs absent). FREEZE it the moment x reaches grest so it stays parked on the coupling
    // tap. If held by an input it never reaches grest and gate2's input block stays empty.
    local v1 = this.BuildAndLaunch(g1.wdepot, g1eDepot);
    local g1x = this.Tx(v1);
    local g1Settled = false;
    local g1Held = false;
    local lastH = -999, stillH = 0, relaunches = 0;
    for (local s = 0; s < 48; s++) {
        GSController.Sleep(10);
        local cx = this.Tx(v1);
        if (cx >= 0) g1x = cx;
        if (cx >= grest && this.Ty(v1) == g1.Y) {
            // gate1 passed (NOR=1): freeze it dead on the coupling rest tile so it OCCUPIES
            // gate2's input block. Confirm it actually stayed put (stationary, on the lane).
            GSVehicle.StartStopVehicle(v1); g1x = cx;
            for (local q = 0; q < 6; q++) {
                GSController.Sleep(6);
                if (this.Tx(v1) == grest && this.Ty(v1) == g1.Y) g1Settled = true; else g1Settled = false;
            }
            break;
        }
        // stall vs held: a held NOR=0 reader parks AT the reader signal (cx ~ g1.sigx-1 = 18). A
        // STALLED reader (a dropped Start on a throttled server) sits BELOW the signal region
        // (cx < g1.sigx-1), barely past the depot, and never advances (the g1x=13/-1 failures).
        if (cx == lastH) stillH++; else stillH = 0;
        lastH = cx;
        if (cx >= g1.sigx - 1 && cx < grest && stillH >= 3) { g1Held = true; break; }   // genuinely held
        // STALL RECOVERY: stuck below the signal region (a dropped Start on a throttled server,
        // the g1x=13/-1 failures). Rebuild the reader cleanly via BuildAndLaunch, which itself
        // confirms egress. A couple of bounded relaunches turn the occasional launch flake into a
        // clean pass. (We do NOT hand-toggle a lane-stalled train: a blind StartStop can stop a
        // moving one. A fresh reader from the west depot is the reliable recovery.)
        if (cx >= 0 && cx < g1.sigx - 1 && stillH >= 4 && relaunches < 2) {
            relaunches++;
            if (GSVehicle.IsValidVehicle(v1)) GSVehicle.SellVehicle(v1);
            GSController.Sleep(8);
            v1 = this.BuildAndLaunch(g1.wdepot, g1eDepot);
            lastH = -999; stillH = 0;
        }
    }
    // If gate1 neither settled at grest nor was confirmed held in the loop, give it one more
    // short stability window so gate2 does not race a gate1 reader that is still crawling.
    if (!g1Settled && !g1Held) {
        local last = this.Tx(v1), stillCount = 0;
        for (local q = 0; q < 12; q++) {
            GSController.Sleep(8);
            local cx = this.Tx(v1);
            if (cx >= 0) g1x = cx;
            if (cx == last) stillCount++; else stillCount = 0;
            last = cx;
            if (stillCount >= 3 && cx < grest) break;   // held, stable, short of grest
        }
    }
    GSController.Sleep(8);

    // Run gate2's reader; its raw final x is the OR output (x > g2sigx => OR 1). Built and driven
    // inline (not RunReader) since gate2's geometry here is the co-located one, not a Geom table.
    // BuildAndLaunch already confirms it left its depot (defeats the launch-stall, the run-4
    // no-readout failure). We then poll until its x is STABLE so the readout is its true final
    // position, not a mid-transit sample. A passing reader comes to rest well past g2sigx; a held
    // reader stops AT g2sigx. Either way the final tile is > g2bx (the first lane tile). If the
    // reader never gets past the start (a wedged launch), we rebuild it and try again.
    local g2x = g2bx - 1;
    local v2 = this.BuildAndLaunch(g2wDepot, g2eDepot);
    for (local launchTry = 0; launchTry < 3; launchTry++) {
        local last2 = -999, still2 = 0, advanced = false;
        g2x = g2bx - 1;
        for (local s = 0; s < 24; s++) {
            GSController.Sleep(15);
            local cx = this.Tx(v2);
            if (cx >= 0) g2x = cx;
            if (cx > g2bx) advanced = true;
            if (cx == last2) still2++; else still2 = 0;
            last2 = cx;
            // stable and clearly arrived (past the signal on a pass, or held at the signal on a
            // block): the position has latched, stop polling early.
            if (still2 >= 3 && cx > g2bx) break;
        }
        if (advanced) break;   // reader moved onto the lane, g2x is a real read
        // wedged at the start: scrap and relaunch a fresh reader.
        if (v2 != null && GSVehicle.IsValidVehicle(v2)) GSVehicle.SellVehicle(v2);
        GSController.Sleep(8);
        v2 = this.BuildAndLaunch(g2wDepot, g2eDepot);
    }
    return { g1x = g1x, g2x = g2x, grest = grest, sig2 = g2sigx };
}

function ComputeCellMain::StartOR(g0cell, g1cell) {
    // Verify the coupling is the EMITTED ROUTED NET, not an assumption: there must be a route
    // whose net == gate1.output == gate2's input. (We do not use its bridged path geometry,
    // which is unsolved in game, see STUCK.md #4; we realise the same driver->consumer link as
    // a direct coupling on the shared lane, which is the route's logical content.)
    local link = g0cell.output.net;
    local haveRoute = false;
    foreach (r in this.data.routes) if (r.net == link) { haveRoute = true; break; }
    GSLog.Info("OR: gate1 '" + g0cell.id + "' -> net '" + link + "' -> gate2 '" + g1cell.id
               + "' routedNet=" + haveRoute);

    // Flatten a generous box covering all four copy bands. gate2 is co-located 3 rows below
    // gate1 with its tap at grest = g1.sig2x+2, and its east depot at grest+4, so the eastmost
    // tile is grest+4. The westmost is gate1's west depot at g0cell.x. Bands are 8 rows apart;
    // the last band's gate2 lane is (g0cell.y + 1) + 3 + lastDy.
    local gA = this.GeomAt(g0cell, 0);
    local grest0 = gA.sig2x + 2;
    local xmax = grest0 + 5;   // gate1 east depot at grest+5 (gate2 east depot at grest+4)
    local lastDy = 3 * 8;   // four bands, 8 rows apart
    this.Prepare(g0cell.x - 2, g0cell.y - 2, xmax + 3, gA.Y + 3 + lastDy + 3);
    this.Say("CCEL OR build");

    local r00 = this.RunCopyOR(g0cell, g1cell, 0,  0);
    this.Say("OR c00 " + r00.g1x + "/" + r00.g2x);
    local r01 = this.RunCopyOR(g0cell, g1cell, 8,  1);
    this.Say("OR c01 " + r01.g1x + "/" + r01.g2x);
    local r10 = this.RunCopyOR(g0cell, g1cell, 16, 2);
    this.Say("OR c10 " + r10.g1x + "/" + r10.g2x);
    local r11 = this.RunCopyOR(g0cell, g1cell, 24, 3);

    // Encode SHORT: gate2 signal x then the four gate2 raw reader x. Judge: x > sig => OR 1.
    // Expected OR(a,b) = 0,1,1,1.
    local nm = "OR s" + r00.sig2 + " " + r00.g2x + " " + r01.g2x + " " + r10.g2x + " " + r11.g2x;
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function ComputeCellMain::Start() {
    GSLog.Info("computecell: starting.");
    this.data = GetScenarioData();
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID) {
        GSLog.Info("computecell: waiting for company (run start_ai)...");
        GSController.Sleep(25);
    }
    this.company = GSCompany.COMPANY_FIRST;
    local mode = GSCompanyMode(this.company);
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    this.Say("CCEL build");
    local rt = GSRailTypeList().Begin();
    GSRail.SetCurrentRailType(rt);
    this.eng = this.PickEngine(rt);

    // Collect the buildable NOR/NOT cells from the placement.
    local nors = [];
    foreach (c in this.data.cells) if (c.type == "NOR") nors.append(c);
    if (nors.len() == 0) {
        this.Say("CCEL NOCELL");
        while (true) GSController.Sleep(74);
    }

    // STAGE 2: a 2-cell OR chain = NOT(NOR(a,b)). Detect it: a 2-input NOR (gate1) feeding a
    // 1-input NOR/NOT (gate2) whose input net is gate1's output. Both cells and the link come
    // from the placement. If found, run the OR chain; otherwise fall through to SC1.
    if (nors.len() == 2) {
        local g0c = null; local g1c = null;
        foreach (c in nors) {
            if (c.inputs.len() == 2) g0c = c;
            else if (c.inputs.len() == 1) g1c = c;
        }
        if (g0c != null && g1c != null && g1c.inputs[0].net == g0c.output.net) {
            this.StartOR(g0c, g1c);   // never returns
        }
    }

    // SC1: a single NOR2 cell. Pick the first NOR (non-const) placed cell.
    local cell = nors[0];

    // Flatten a generous box around this cell's footprint (origin-relative, from placement).
    local g0 = this.Geom(cell);
    this.Prepare(cell.x - 2, cell.y - 2, g0.eastx + 2, g0.Y + 3);
    local g = this.StampCell(cell);
    this.Say("CCEL stamped");

    // Sweep the input combos. For a 2-input cell that is 00,01,10,11; the readout encodes
    // the four RAW reader x in the order o00 o01 o10 o11 (NOR = 1,0,0,0 expected).
    local combos = (g.n >= 2) ? [0, 1, 2, 3] : [0, 1];
    local xs = [];
    foreach (b in combos) {
        local fx = this.Case(g, b);
        xs.append(fx);
        // live progress so a watcher sees the sweep advance.
        this.Say("CCEL b" + b + " x" + fx);
    }

    // Encode SHORT: reader signal x then the raw reader x per combo. External judge:
    // x > SIGX => output bit 1. Expected NOR(a,b) = 1,0,0,0.
    local nm = "SC1 s" + g.sigx;
    foreach (fx in xs) nm += " " + fx;
    while (true) { this.Say(nm); GSController.Sleep(74); }
}

function ComputeCellMain::Save() { return {}; }
function ComputeCellMain::Load(version, data) {}
