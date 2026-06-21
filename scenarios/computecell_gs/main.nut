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
    for (local x = x0; x <= x1; x++)
        for (local y = y0; y <= y1; y++)
            GSTile.DemolishTile(GSMap.GetTileIndex(x, y));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
    GSTile.LevelTiles(GSMap.GetTileIndex(x0, y0), GSMap.GetTileIndex(x1, y1));
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
function ComputeCellMain::ParkInput(inDepot, tx, Y) {
    local v = GSVehicle.BuildVehicle(inDepot, this.eng);
    GSOrder.AppendOrder(v, GSMap.GetTileIndex(tx, Y), GSOrder.OF_NON_STOP_INTERMEDIATE);
    if (GSVehicle.IsStoppedInDepot(v)) GSVehicle.StartStopVehicle(v);
    for (local w = 0; w < 40; w++) {
        GSController.Sleep(5);
        if (GSVehicle.IsValidVehicle(v)
            && GSMap.GetTileX(GSVehicle.GetLocation(v)) == tx
            && GSMap.GetTileY(GSVehicle.GetLocation(v)) == Y) {
            GSVehicle.StartStopVehicle(v);
            break;
        }
    }
    return v;
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
function ComputeCellMain::RunCopyOR(g0cell, g1cell, dy, bits) {
    // gate1 on the band row, gate2 three rows below; the coupling runs on the row between them.
    local g1 = this.GeomAt(g0cell, dy);          // gate1 = NOR2
    local g2 = this.GeomAt(g1cell, dy + 3);      // gate2 = NOT, on the lower lane
    // GREST: gate1's reader natural REST tile when it passes. A passing reader coasts ~2 tiles
    // past the terminating signal and stops (the norchain "held a tile early" behaviour), so its
    // output train always rests just east of gate1's terminating signal. We tap gate1's output
    // bit there, NOT at a distant tile it never reaches. Derived from gate1's placed geometry.
    local grest = g1.sig2x + 2;
    // Couple into gate2's input block at the tile just WEST of its terminating signal
    // (sig2x - 1). That tile is in the protected input block but is NOT a tap, so it has no
    // feeder depot north of it for the coupling vertical to collide with. Placement-derived.
    local cinx  = g2.sig2x - 1;
    local crow  = g1.Y + 1;     // intermediate coupling row, clear between the two lanes.

    // Build gate1: lane bx..grest+1, west depot, an east depot just past grest so gate1's lane
    // east of its terminating signal is a THROUGH block (a dead end here triggers the norchain
    // "reader held a tile early" misfire, observed when the east depot is removed). The reader
    // coasts to grest and rests there on pass. Reader + terminating signals, input taps follow.
    for (local x = g1.bx; x <= grest; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, g1.Y), GSRail.RAILTRACK_NE_SW);
    g1.wdepot <- GSMap.GetTileIndex(g1.wdepot_x, g1.Y);
    GSRail.BuildRailDepot(g1.wdepot, GSMap.GetTileIndex(g1.bx, g1.Y));
    local g1eDepot = GSMap.GetTileIndex(grest + 1, g1.Y);
    GSRail.BuildRailDepot(g1eDepot, GSMap.GetTileIndex(grest, g1.Y));
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
    // Stamp gate2 normally (with its east depot, where its reader rests on pass).
    this.StampGeom(g1cell, g2, true);

    // COUPLING = the emitted routed net gate1.output -> gate2.input, realised in track with NO
    // signals so gate1's output block and gate2's input block are ONE block. We branch off a
    // MID-BLOCK tile of gate1's output block (ctap = sig2x + 1, clear of the east-depot-adjacent
    // grest tile), run an intermediate row east, then drop into gate2's input block:
    //   (ctap, g1.Y) -> down -> (ctap, crow) -> east along crow -> (cinx, crow)
    //                -> down -> (cinx, g2.Y) = a non-tap tile of gate2's input block.
    // A gate1 reader resting in its output block therefore occupies gate2's input block; a held
    // gate1 (reader west of its signals) leaves that block empty.
    // Corner pieces chosen for BLOCK CONNECTIVITY (each tile shares a track edge with the next):
    // +x (east) exits the SW edge / enters the NE edge; +y (south) exits SE / enters NW.
    local ctap = g1.sig2x + 1;
    GSRail.BuildRailTrack(GSMap.GetTileIndex(ctap, g1.Y), GSRail.RAILTRACK_NE_SE);    // lane (NE) + branch down (SE)
    GSRail.BuildRailTrack(GSMap.GetTileIndex(ctap, crow), GSRail.RAILTRACK_NW_SW);    // arrive from N (NW), turn east (SW)
    for (local x = ctap + 1; x < cinx; x++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(x, crow), GSRail.RAILTRACK_NE_SW);   // east run
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cinx, crow), GSRail.RAILTRACK_NE_SE);    // arrive from W (NE), turn down (SE)
    for (local y = crow + 1; y < g2.Y; y++)
        GSRail.BuildRailTrack(GSMap.GetTileIndex(cinx, y), GSRail.RAILTRACK_NW_SE);   // vertical
    GSRail.BuildRailTrack(GSMap.GetTileIndex(cinx, g2.Y), GSRail.RAILTRACK_NW_NE);    // arrive from N (NW), join lane (NE)

    // Pre-park gate1's primary inputs a,b per the combo.
    for (local i = 0; i < g1.n; i++)
        if (bits & (1 << i)) this.ParkInput(g1.inDepots[i], g1.taps[i], g1.Y);
    GSController.Sleep(8);

    // Run gate1's reader toward its east depot; it coasts to grest and rests there iff it passes
    // (inputs absent). FREEZE it the moment x reaches grest so it stays parked on the coupling
    // tap. If held by an input it never reaches grest (stays west of sig19) and gate2's input
    // block stays empty.
    local v1 = GSVehicle.BuildVehicle(g1.wdepot, this.eng);
    GSOrder.AppendOrder(v1, g1eDepot, GSOrder.OF_NON_STOP_INTERMEDIATE);
    GSController.Sleep(5);
    for (local r = 0; r < 8; r++) {
        if (GSVehicle.IsStoppedInDepot(v1)) GSVehicle.StartStopVehicle(v1);
        GSController.Sleep(4);
        if (!GSVehicle.IsStoppedInDepot(v1)) break;
    }
    // A passing reader coasts to grest and rests on gate1's output block (which the coupling
    // ties into gate2's input block). Freeze it there. A held reader never reaches grest.
    local g1x = this.Tx(v1);
    for (local s = 0; s < 30; s++) {
        GSController.Sleep(10);
        local cx = this.Tx(v1);
        if (cx >= 0) g1x = cx;
        if (cx >= grest && this.Ty(v1) == g1.Y) { GSVehicle.StartStopVehicle(v1); g1x = cx; break; }
    }
    GSController.Sleep(8);

    // Run gate2's reader; its raw final x is the OR output (x > gate2.sigx => OR 1).
    local rr = this.RunReader(g2);
    return { g1x = g1x, g2x = rr.fx, grest = grest, sig2 = g2.sigx };
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

    // Flatten a generous box covering all four copy bands. The eastmost tile is gate2's east
    // depot (the coupling tap cinx = gate2.taps[0] lies west of it); the westmost is gate1's
    // origin. Bands are 8 rows apart; the last band's gate2 lane is g1cell.y + 3 + lastDy.
    local gA = this.GeomAt(g0cell, 0);
    local gB = this.GeomAt(g1cell, 3);
    local xmax = (gB.eastx > gA.eastx ? gB.eastx : gA.eastx);
    local lastDy = 3 * 8;   // four bands, 8 rows apart
    this.Prepare(g0cell.x - 2, g0cell.y - 2, xmax + 3, g1cell.y + 3 + lastDy + 3);
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
