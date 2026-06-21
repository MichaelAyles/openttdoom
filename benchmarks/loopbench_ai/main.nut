/*
 * LoopBench: a benchmark-map builder AI for the openttdoom speed fork.
 *
 * It founds a company and builds large rectangular rail loops on flat ground,
 * with PBS one-way signals all the way around each loop so trains run one
 * direction and chase each other. A depot taps each loop; we build N engine-only
 * trains (no wagons, so no station/cargo loading) and give each two waypoints on
 * the loop so they circulate forever. With many trains chasing each other through
 * PBS signals this hammers exactly the per-train hot path we benchmark:
 * Train::Tick -> TrainController -> ChooseTrainTrack -> YAPF + signal reservation.
 *
 * Design notes for ACTUALLY CIRCULATING (avoid gridlock):
 *  - Loops are large (long perimeter) so many trains fit with slack.
 *  - PBS one-way signals are spaced a few tiles apart (one train per block).
 *  - Trains are released from a depot stub; non-stop waypoint orders spread them
 *    out around the ring.
 *  - Train count per loop is kept well below the number of signal blocks so the
 *    ring never saturates into a standstill.
 */

class LoopBench extends AIController {
	built = false;
	total_trains = 0;
}

function LoopBench::Save() { return { built = this.built }; }
function LoopBench::Load(version, data) { if ("built" in data) this.built = data.built; }

function LoopBench::Start()
{
	// Idempotent on reload: if this company already has vehicles, the map was
	// already built. Do not build again (that would mutate the benchmark map on
	// every load). Just report motion and idle.
	{
		local existing = AIVehicleList();
		if (existing.Count() > 0) {
			AILog.Info("LOOPBENCH RESUME, already built, trains=" + existing.Count());
			while (true) { this.ReportMotion(); this.Sleep(150); }
		}
	}

	AICompany.SetName("LoopBench");
	AICompany.SetLoanAmount(AICompany.GetMaxLoanAmount());

	local railtypes = AIRailTypeList();
	if (railtypes.Count() == 0) { AILog.Error("no rail type"); return; }
	local rt = railtypes.Begin();
	AIRail.SetCurrentRailType(rt);

	local engine = this.PickEngine(rt);
	if (engine == null) { AILog.Error("no usable rail engine"); return; }
	AILog.Info("engine " + engine + " " + AIEngine.GetName(engine) + " speed " + AIEngine.GetMaxSpeed(engine));

	local per_loop = this.GetSetting("num_trains");

	// A DENSE GRID of small single-train loops. One train per closed loop can
	// never deadlock (it owns the whole ring), so every train circulates forever
	// and exercises the per-train hot path (Train::Tick + signal reservation +
	// YAPF at each signal) continuously. Many such loops give many MOVING trains.
	// Loop footprint is LOOP x LOOP tiles, on a PITCH grid, within the 256 map.
	local LOOP = 12;     // ring side length (so perimeter ~48 tiles, several signals)
	local PITCH = 16;    // grid spacing between loop origins
	local LO = 4;        // first origin
	local HI = 240;      // last usable origin (leave map border)

	local count = 0;
	local placed = 0;
	for (local oy = LO; oy + LOOP + 2 <= HI; oy += PITCH) {
		for (local ox = LO; ox + LOOP + 2 <= HI; ox += PITCH) {
			local n = this.BuildLoop(ox, oy, engine, 1);
			count += n;
			placed++;
		}
	}
	AILog.Info("placed " + placed + " loops, " + count + " trains");

	this.total_trains = count;
	this.built = true;
	AILog.Info("LOOPBENCH READY n=" + count);

	while (true) { this.ReportMotion(); this.Sleep(150); }
}

function LoopBench::ReportMotion()
{
	local vl = AIVehicleList();
	local total = 0, moving = 0, sumspd = 0, indepot = 0, running = 0, stopped = 0;
	foreach (v, _ in vl) {
		if (AIVehicle.GetVehicleType(v) != AIVehicle.VT_RAIL) continue;
		total++;
		local s = AIVehicle.GetCurrentSpeed(v);
		sumspd += s;
		if (s > 0) moving++;
		if (AIVehicle.IsInDepot(v)) indepot++;
		local st = AIVehicle.GetState(v);
		if (st == AIVehicle.VS_RUNNING) running++;
		else if (st == AIVehicle.VS_STOPPED) stopped++;
	}
	local avg = (total > 0) ? (sumspd / total) : 0;
	AILog.Info("MOTION total=" + total + " moving=" + moving + " avgspeed=" + avg
		+ " indepot=" + indepot + " running=" + running + " stopped=" + stopped);
}

function LoopBench::PickEngine(rt)
{
	local list = AIEngineList(AIVehicle.VT_RAIL);
	local best = null, best_speed = -1;
	foreach (e, _ in list) {
		if (!AIEngine.IsValidEngine(e)) continue;
		if (AIEngine.IsWagon(e)) continue;
		if (!AIEngine.CanRunOnRail(e, rt)) continue;
		if (!AIEngine.HasPowerOnRail(e, rt)) continue;
		local s = AIEngine.GetMaxSpeed(e);
		if (s > best_speed) { best_speed = s; best = e; }
	}
	return best;
}

/*
 * Build a large rectangular ring whose corners are (ox,oy) .. (ox+W, oy+H).
 * Returns trains built.
 *
 * The ring is laid as straight rail along each side (BuildRail spans the whole
 * side in one call and auto-curves into the next), then we explicitly build the
 * four corner curves. We verify continuity with AreTilesConnected and log it.
 */
function LoopBench::BuildLoop(ox, oy, engine, num_trains)
{
	local W = 12, H = 12;
	local x0 = ox, y0 = oy, x1 = ox + W, y1 = oy + H;

	// Build the ring as four BuildRail spans that each run THROUGH a corner into
	// the next side. Going clockwise: bottom L->R, right B->T, top R->L, left T->B.
	// Each span starts one tile into the previous side so the curve forms, and ends
	// one tile into the next side. This guarantees continuous corners.
	// Bottom then into right side:
	AIRail.BuildRail(AIMap.GetTileIndex(x0 + 1, y0), AIMap.GetTileIndex(x0, y0), AIMap.GetTileIndex(x1, y0));
	AIRail.BuildRail(AIMap.GetTileIndex(x0, y0),     AIMap.GetTileIndex(x1, y0), AIMap.GetTileIndex(x1, y1));
	AIRail.BuildRail(AIMap.GetTileIndex(x1, y0),     AIMap.GetTileIndex(x1, y1), AIMap.GetTileIndex(x0, y1));
	AIRail.BuildRail(AIMap.GetTileIndex(x1, y1),     AIMap.GetTileIndex(x0, y1), AIMap.GetTileIndex(x0, y0));
	AIRail.BuildRail(AIMap.GetTileIndex(x0, y1),     AIMap.GetTileIndex(x0, y0), AIMap.GetTileIndex(x1, y0));

	local okBL = AIRail.AreTilesConnected(AIMap.GetTileIndex(x0 + 1, y0), AIMap.GetTileIndex(x0, y0), AIMap.GetTileIndex(x0, y0 + 1));
	local okBR = AIRail.AreTilesConnected(AIMap.GetTileIndex(x1 - 1, y0), AIMap.GetTileIndex(x1, y0), AIMap.GetTileIndex(x1, y0 + 1));
	local okTL = AIRail.AreTilesConnected(AIMap.GetTileIndex(x0 + 1, y1), AIMap.GetTileIndex(x0, y1), AIMap.GetTileIndex(x0, y1 - 1));
	local okTR = AIRail.AreTilesConnected(AIMap.GetTileIndex(x1 - 1, y1), AIMap.GetTileIndex(x1, y1), AIMap.GetTileIndex(x1, y1 - 1));
	AILog.Info("corners BL=" + okBL + " BR=" + okBR + " TL=" + okTL + " TR=" + okTR);

	// Waypoints on bottom and top (mid-side) for circulating orders.
	local wp_b = AIMap.GetTileIndex(x0 + (W / 2), y0);
	local wp_t = AIMap.GetTileIndex(x0 + (W / 2), y1);
	AIRail.BuildRailWaypoint(wp_b);
	AIRail.BuildRailWaypoint(wp_t);

	// One-way PBS signals clockwise around the ring, every 4 tiles, so each block
	// holds one train and trains chase each other. Skip the left side near the
	// depot tap so trains can merge out.
	this.RingSignals(x0, y0, x1, y1, 4);

	// Depot tapped into the LEFT side via a spur, set back from the ring so the
	// merge is a simple curve. Depot at (x0-1, y0+5) opening east (+x) onto a spur
	// tile (x0, y0+5) which is on the left side of the ring.
	local ring_tap = AIMap.GetTileIndex(x0, y0 + 5);
	local depot    = AIMap.GetTileIndex(x0 - 1, y0 + 5);
	AIRail.BuildRailDepot(depot, ring_tap);

	// Build and start trains.
	local built = 0;
	for (local i = 0; i < num_trains; i++) {
		local t = AIVehicle.BuildVehicle(depot, engine);
		if (!AIVehicle.IsValidVehicle(t)) { AILog.Warning("BuildVehicle failed i=" + i + " err=" + AIError.GetLastErrorString()); break; }
		AIOrder.AppendOrder(t, wp_b, AIOrder.OF_NON_STOP_INTERMEDIATE | AIOrder.OF_NON_STOP_DESTINATION);
		AIOrder.AppendOrder(t, wp_t, AIOrder.OF_NON_STOP_INTERMEDIATE | AIOrder.OF_NON_STOP_DESTINATION);
		AIVehicle.StartStopVehicle(t);
		built++;
	}
	return built;
}

/*
 * Place one-way PBS signals around the ring at the given spacing, all pointing
 * clockwise (bottom +x, right +y, top -x, left -y) so trains run one way.
 * The signal "front" tile is the next tile in the travel direction.
 */
function LoopBench::RingSignals(x0, y0, x1, y1, step)
{
	for (local x = x0 + 2; x < x1 - 1; x += step) this.Sig(x, y0, x + 1, y0);  // bottom +x
	for (local y = y0 + 2; y < y1 - 1; y += step) this.Sig(x1, y, x1, y + 1);  // right +y
	for (local x = x1 - 2; x > x0 + 1; x -= step) this.Sig(x, y1, x - 1, y1);  // top -x
	for (local y = y1 - 2; y > y0 + 1; y -= step) this.Sig(x0, y, x0, y - 1);  // left -y
}

function LoopBench::Sig(tx, ty, fx, fy)
{
	AIRail.BuildSignal(AIMap.GetTileIndex(tx, ty), AIMap.GetTileIndex(fx, fy), AIRail.SIGNALTYPE_PBS_ONEWAY);
}
