/*
 * openttdoom GameScript builder (GSController).
 *
 * On Start() this reads the baked scenario data table produced by
 * place_and_route (scenario_data.nut, format defined by Scenario.to_nut() in
 * place_and_route/scenario.py) and constructs the design on the map:
 *
 *   - for every cell, stamp a NOR tile at (x, y),
 *   - for every route, lay track along the path,
 *   - place the clock train on its loop,
 *   - set the input pads so they can be poked,
 *   - map outputs to framebuffer signal tiles.
 *
 * HONEST STATUS. This is a skeleton. The control flow, the data walk and the
 * real GS API calls are here, but the exact track pieces, signal types, signal
 * front tiles and clock release timing that make a NOR tile actually compute are
 * NOT solved. Every such spot is marked TODO(human). Do not trust the geometry
 * in the stamp_* helpers, it is illustrative scaffolding. The open research
 * problem is turning the reference gate constructions (see ../GATE_DESIGN.md)
 * into exact coordinates. STUCK.md lists what is blocked and why. We deliberately
 * do not fabricate working geometry.
 *
 * This file has not been run. There is no OpenTTD GS runtime in the build
 * environment, so it is unverified Squirrel. Syntax and API names follow the
 * documented GS API (GSRail, GSMap, GSVehicle, GSCompanyMode, GSSign, GSLog).
 */

require("scenario_data.nut");   // defines GetScenarioData(), see place_and_route

class OpenttdoomMain extends GSController {
    data = null;          // the baked scenario table
    company = null;       // company we build as, see PickCompany()

    constructor() {
    }
}

/*
 * Coordinate helper. The data table uses OpenTTD tile (x, y); the GS API uses a
 * flat TileIndex. GSMap.GetTileIndex does the conversion.
 */
OFFSET <- 8;   // shift the whole design away from the map border (edge tiles cannot build)
function OpenttdoomMain::Tile(x, y) {
    return GSMap.GetTileIndex(x + OFFSET, y + OFFSET);
}

/*
 * Building anything needs a company context. A GameScript runs as a deity (no
 * company) by default, and GSRail/GSTile build calls require GSCompanyMode set
 * to a valid company. See STUCK.md: this is a genuine open item, the scenario
 * must provide a company for us to borrow, or a human starts one before running.
 *
 * TODO(human): decide the company story. Options to evaluate:
 *   - require the scenario to be opened in a game that already has company 0,
 *   - or have the human found a company first, then run "start" from console,
 *   - or investigate whether deity-built rail (town owned) is acceptable for a
 *     pure-logic map where economy is irrelevant.
 * Until this is settled, build calls below will be rejected and nothing stamps.
 */
function OpenttdoomMain::PickCompany() {
    // GSCompany.COMPANY_FIRST is the first human/AI company slot.
    local c = GSCompany.COMPANY_FIRST;
    if (GSCompany.ResolveCompanyID(c) == GSCompany.COMPANY_INVALID) {
        GSLog.Warning("openttdoom: no valid company to build as. See STUCK.md.");
    }
    return c;
}

function OpenttdoomMain::Start() {
    GSLog.Info("openttdoom builder: starting.");
    this.data = GetScenarioData();
    GSLog.Info("openttdoom: design '" + this.data.name + "', "
               + this.data.cells.len() + " cells, "
               + this.data.routes.len() + " routes.");

    // Wait for a buildable company (single-player already has one; on a dedicated
    // server, create one with the console command `start_ai`). Build as it.
    while (GSCompany.ResolveCompanyID(GSCompany.COMPANY_FIRST) == GSCompany.COMPANY_INVALID) {
        GSLog.Info("openttdoom: waiting for a company to build as (run start_ai)...");
        GSController.Sleep(25);
    }
    this.company = GSCompany.COMPANY_FIRST;
    GSLog.Info("openttdoom: building as company " + this.company);
    this.Build();

    GSLog.Info("openttdoom builder: build pass complete (see TODO markers).");

    // Keep the script alive so the design can be poked and inspected from the
    // console. Real input poking and framebuffer readout are driven externally
    // (see readme.txt: the `script` console command).
    while (true) {
        GSController.Sleep(74);   // ~ one in-game day, idle.
    }
}

function OpenttdoomMain::Build() {
    local mode = GSCompanyMode(this.company);   // build as this company
    // Max out the loan so the whole design can be afforded (we screenshot immediately,
    // so interest does not matter).
    GSCompany.SetLoanAmount(GSCompany.GetMaxLoanAmount());
    GSLog.Info("openttdoom: bank balance " + GSCompany.GetBankBalance(this.company));

    // Pick the first available rail type to build with.
    local rtypes = GSRailTypeList();
    if (rtypes.Count() == 0) { GSLog.Error("openttdoom: no rail type available to build with"); return; }
    GSRail.SetCurrentRailType(rtypes.Begin());
    GSLog.Info("openttdoom: building with rail type " + rtypes.Begin());

    foreach (cell in this.data.cells) {
        this.StampCell(cell);
    }
    foreach (route in this.data.routes) {
        this.LayRoute(route);
    }
    this.PlaceClock(this.data.clock);
    foreach (pad in this.data.io) {
        if (pad.kind == "input")  this.SetInputPad(pad);
        else                      this.MapOutputPad(pad);
    }
    if (this.data.framebuffer != null) {
        this.WireFramebuffer(this.data.framebuffer);
    }
}

/*
 * Stamp one NOR tile. type is one of NOR / CONST0 / CONST1 (the buildable set).
 * cell has .x .y .w .h .inputs (array of {net,x,y}) and .output ({net,x,y}|null).
 *
 * This is THE hard piece. The reference gate constructions give the idea (input
 * taps read with two-way signals, a combo/exit presignal evaluating NOR over the
 * input blocks, an output register track held for one clock period). They do NOT
 * give exact tile-by-tile coordinates, and the layout depends on which sides the
 * routed nets enter and leave, the rail type, and the clock release timing.
 */
function OpenttdoomMain::StampCell(cell) {
    GSLog.Info("  stamp " + cell.type + " '" + cell.id
               + "' at (" + cell.x + "," + cell.y + ") "
               + cell.w + "x" + cell.h);

    if (cell.type == "CONST0" || cell.type == "CONST1") {
        // TODO(human): CONST tiles are hardwired track holding a permanent train
        // (CONST1) or permanently empty track (CONST0). Decide the exact tile
        // and, for CONST1, spawn a parked train. No real geometry yet.
        return;
    }

    // NOR tile. The footprint box is cell.x..cell.x+cell.w, cell.y..+cell.h.
    //
    // TODO(human): lay the real NOR construction inside this box. Concretely,
    // each of the following needs exact (tile, track-piece) and (tile, front,
    // signal-type) tuples derived from a verified in-game NOR gate:
    //
    //   1. an input tap per cell.input, read with a two-way signal so reading
    //      the bit does not consume the train,
    //   2. a combo or entry pre-signal arrangement whose aspect is the NOR of
    //      the input occupancies (red iff all inputs present, see GATE_DESIGN.md),
    //   3. an output register track at cell.output that holds the result for one
    //      full clock period,
    //   4. a clock-release tap so this tile samples on the shared clock edge.
    //
    // The calls below show the SHAPE of the work and are NOT a correct gate.
    // They lay a single straight piece per pin as a placeholder so routing has
    // something to attach to. Replace wholesale once the geometry is solved.

    foreach (pin in cell.inputs) {
        // placeholder: one straight track piece at the input pin tile.
        // TODO(human): real input tap + two-way read signal here.
        GSRail.BuildRailTrack(this.Tile(pin.x, pin.y), GSRail.RAILTRACK_NE_SW);
    }
    if (cell.output != null) {
        // placeholder: one straight track piece at the output pin tile.
        // TODO(human): real output register track + read signal here.
        GSRail.BuildRailTrack(this.Tile(cell.output.x, cell.output.y),
                              GSRail.RAILTRACK_NE_SW);
    }
    // TODO(human): build the NOR evaluation (presignals) inside the box and the
    // clock-release tap. Nothing here yet, so this tile does NOT compute.
}

/*
 * Lay track for one net along its routed path. route has .net, .path (an ordered
 * list of [x, y] tiles from place_and_route) and .bridges (the subset of path
 * tiles where THIS net is the one carried OVER a perpendicular crossing).
 *
 * The channel router lays every net on a unique horizontal trunk row reached by
 * unique-column vertical risers, and two nets only ever meet at a clean
 * perpendicular crossing. On the substrate that crossing is a BRIDGE: the trunk
 * (this net, on a bridge tile) passes over the perpendicular riser of the other
 * net. So for every tile in route.bridges we build a bridge over the crossing
 * instead of plain track; every other tile is laid as ordinary track.
 *
 * Laying a connected run of track means, for each interior tile, choosing the
 * track piece that connects the previous tile to the next one (straight or one
 * of the four curves). That choice is a function of the three-tile turn, which
 * we can compute from the path. The signal placement along the run (to keep the
 * carrier train moving one way) still needs the gate timing to be settled.
 */
function OpenttdoomMain::LayRoute(route) {
    local path = route.path;
    if (path.len() < 2) return;

    // Set of bridge tiles for O(1) lookup while walking the path. The key is the
    // packed TileIndex so it matches what we build on.
    local bridge_set = {};
    foreach (b in route.bridges) {
        bridge_set[this.Tile(b[0], b[1])] <- true;
    }
    GSLog.Info("  route '" + route.net + "' len " + path.len()
               + " bridges " + route.bridges.len());

    for (local i = 0; i < path.len() - 1; i++) {
        local a = path[i];
        local b = path[i + 1];
        local tile = this.Tile(a[0], a[1]);
        if (tile in bridge_set) {
            this.LayBridge(route, a, (i > 0 ? path[i - 1] : a), b);
        } else {
            local piece = this.TrackPieceBetween(
                (i > 0 ? path[i - 1] : a), a, b);
            // TODO(human): TrackPieceBetween covers straights; curve selection at
            // bends is not handled, nor diagonal moves.
            GSRail.BuildRailTrack(tile, piece);
        }
    }
    // last tile of the run (trunk ends are always plain track, never a bridge).
    local last = path[path.len() - 1];
    GSRail.BuildRailTrack(this.Tile(last[0], last[1]), GSRail.RAILTRACK_NE_SW);

    // TODO(human): place one-way signals along the run so the carrier train
    // moves in the routed direction and presents its bit at the far end on the
    // clock edge. Spacing and signal type depend on the gate timing.
}

/*
 * Build a single-tile bridge carrying THIS net's (horizontal) trunk over the
 * perpendicular (vertical) riser of another net at tile `a`. prev and nxt are the
 * path neighbours, so the bridge runs along the trunk direction (prev -> a -> nxt).
 *
 * The data flow is wired: every tile place_and_route marked as a bridge crossing
 * arrives here and we call GSBridge.BuildBridge over it. The exact bridge type
 * lookup and the head/ramp geometry that make a one-tile overpass land cleanly on
 * the OpenTTD grid still need calibration in game, so that part stays TODO(human),
 * but the crossing list now drives real bridge construction rather than plain
 * track that would short the two signals together.
 */
function OpenttdoomMain::LayBridge(route, a, prev, nxt) {
    // Bridge end tiles: one tile back along the trunk and one tile forward, so the
    // span clears the perpendicular riser underneath the crossing tile `a`.
    local head = this.Tile(prev[0], prev[1]);
    local tail = this.Tile(nxt[0], nxt[1]);
    GSLog.Info("    bridge for '" + route.net + "' over crossing at ("
               + a[0] + "," + a[1] + ")");

    // TODO(human): pick a buildable rail bridge type for the span length and the
    // current rail type, e.g.
    //   local types = GSBridgeList_Length(2);
    //   local bt = types.IsEmpty() ? -1 : types.Begin();
    //   GSBridge.BuildBridge(GSVehicle.VT_RAIL, bt, head, tail);
    // The head/tail orientation and exact ramp tiles need in-game calibration;
    // until then this records the intent and the crossing data flows through.
    local types = GSBridgeList_Length(GSMap.DistanceManhattan(head, tail) + 1);
    if (!types.IsEmpty()) {
        GSBridge.BuildBridge(GSVehicle.VT_RAIL, types.Begin(), head, tail);
    }
}

/*
 * Choose a straight track piece for the step from `a` to `b`. Returns a
 * GSRail.RAILTRACK_* constant. `prev` is the tile before `a` (equals `a` at the
 * start of a run) and is where curve selection WOULD use the incoming direction.
 *
 * Only the two axis-aligned straights are handled. Curves and diagonals are
 * TODO(human).
 */
function OpenttdoomMain::TrackPieceBetween(prev, a, b) {
    local dx = b[0] - a[0];
    local dy = b[1] - a[1];
    if (dy == 0 && dx != 0) return GSRail.RAILTRACK_NE_SW;  // along X
    if (dx == 0 && dy != 0) return GSRail.RAILTRACK_NW_SE;  // along Y
    // TODO(human): turns (NW_NE, SW_SE, NW_SW, NE_SE) and diagonal runs.
    GSLog.Warning("    unhandled step at (" + a[0] + "," + a[1] + "), "
                  + "using straight. TODO(human) curve selection.");
    return GSRail.RAILTRACK_NE_SW;
}

/*
 * Place the clock train on its loop. clock has .period, .x, .y.
 * The clock is a single train running a small fixed loop; one lap is one clock
 * edge. period is the intended lap length in ticks.
 */
function OpenttdoomMain::PlaceClock(clock) {
    GSLog.Info("  clock at (" + clock.x + "," + clock.y
               + ") period " + clock.period);
    // TODO(human): build the clock loop track at (clock.x, clock.y) sized so one
    // lap takes `period` ticks, build a depot, buy one train (GSVehicle.BuildVehicle
    // into the depot), give it a non-stop circular order over the loop, and start
    // it. Loop length to ticks depends on train speed and tile count, which needs
    // calibration in game. None of that geometry is solved yet.
}

/*
 * An input pad is a tile a human (or the console) can poke to set a bit. On the
 * substrate, poking means placing or removing a train on the pad's net track.
 */
function OpenttdoomMain::SetInputPad(pad) {
    GSLog.Info("  input pad '" + pad.port + "' net '" + pad.net
               + "' at (" + pad.x + "," + pad.y + ")");
    // TODO(human): build the pad track at (pad.x, pad.y) and a depot beside it so
    // a train can be injected/removed to set the bit. The actual poke (inject a
    // train = 1, remove = 0) is driven later from the console; here we only build
    // the pokeable structure. Geometry unsolved.
}

/*
 * An output pad maps a net to a readable/displayable tile.
 */
function OpenttdoomMain::MapOutputPad(pad) {
    GSLog.Info("  output pad '" + pad.port + "' net '" + pad.net
               + "' at (" + pad.x + "," + pad.y + ")");
    // TODO(human): build the readout structure at (pad.x, pad.y). For the viewer
    // this is a signal whose state mirrors the net's train presence at the clock
    // edge, so the framebuffer reader can sample it. Geometry unsolved.
}

/*
 * Wire the framebuffer: each pixel net drives one on-map signal tile, row-major.
 * fb has .x .y .w .h .pixels (array of net names, "" means unmapped/const-0).
 */
function OpenttdoomMain::WireFramebuffer(fb) {
    GSLog.Info("  framebuffer " + fb.w + "x" + fb.h
               + " at (" + fb.x + "," + fb.y + ")");
    for (local row = 0; row < fb.h; row++) {
        for (local col = 0; col < fb.w; col++) {
            local idx = row * fb.w + col;
            if (idx >= fb.pixels.len()) continue;
            local net = fb.pixels[idx];
            if (net == "") continue;   // unmapped pixel stays dark.
            local tx = fb.x + col;
            local ty = fb.y + row;
            // TODO(human): build the pixel signal at (tx, ty) and tie it to net
            // `net` so the signal shows the pixel bit. One signal per pixel,
            // read by the Python viewer. Geometry unsolved.
        }
    }
}

/*
 * Save/Load. We bake everything from scenario_data.nut on Start(), so there is
 * no dynamic state worth persisting. Returning an empty table is fine.
 */
function OpenttdoomMain::Save() {
    return {};
}

function OpenttdoomMain::Load(version, data) {
    // nothing to restore; the design is rebuilt from the baked table on Start().
}
