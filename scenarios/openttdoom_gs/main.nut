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
function OpenttdoomMain::Tile(x, y) {
    return GSMap.GetTileIndex(x, y);
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

    this.company = this.PickCompany();

    // All construction runs inside a company-mode scope. When `mode` goes out of
    // scope at the end of Build(), the previous (deity) context is restored.
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

    // Pick the rail type to build with. TODO(human): confirm a buildable rail
    // type exists in the scenario's NewGRF set; default rail is usually index 0.
    GSRail.SetCurrentRailType(GSRail.GetRailType(this.Tile(this.data.clock.x,
                                                           this.data.clock.y)));

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
 * Lay track for one net along its routed path. route has .net and .path, an
 * ordered list of [x, y] tiles from place_and_route.
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
    GSLog.Info("  route '" + route.net + "' len " + path.len());

    for (local i = 0; i < path.len() - 1; i++) {
        local a = path[i];
        local b = path[i + 1];
        local piece = this.TrackPieceBetween(
            (i > 0 ? path[i - 1] : a), a, b);
        // TODO(human): TrackPieceBetween covers straights; curve selection at
        // bends and the bridges/tunnels the reference gates use for crossings
        // are not handled. Diagonal moves are also not handled.
        GSRail.BuildRailTrack(this.Tile(a[0], a[1]), piece);
    }
    // last tile of the run.
    local last = path[path.len() - 1];
    GSRail.BuildRailTrack(this.Tile(last[0], last[1]), GSRail.RAILTRACK_NE_SW);

    // TODO(human): place one-way signals along the run so the carrier train
    // moves in the routed direction and presents its bit at the far end on the
    // clock edge. Spacing and signal type depend on the gate timing.
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
