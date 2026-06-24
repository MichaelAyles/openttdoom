/*
 * LoopBench2: a benchmark-map builder that produces GENUINELY CIRCULATING trains
 * that hit a real junction every lap, so the per-train YAPF pathfinder runs
 * repeatedly. This is the workload the openttdoom per-train pathfinding cache
 * targets (a fixed-route train re-choosing the same track at the same junction).
 *
 * Each unit is a large rectangular ring. On the bottom side we add a short
 * dead-end SIDING tapped off the ring via a 3-way point, so at that tile the
 * circulating train faces a real track CHOICE (continue around the ring, or take
 * the siding); YAPF picks "continue" every lap because the train's waypoint is on
 * the ring. The siding is never entered, but its presence forces the choice, which
 * is exactly the recomputed-constant the cache short-circuits.
 *
 * Reliability: rings are large (perimeter ~ 4*SIDE) with sparse PBS one-way
 * signals so one train per ring always has a safe waiting position ahead and
 * circulates without deadlock. The train is built in an inline depot on the left
 * side and released with two waypoint orders (bottom + top mid-side).
 */

class LoopBench2 extends AIController {
	built = false;
	total = 0;
}
function LoopBench2::Save() { return { built = this.built }; }
function LoopBench2::Load(v, d) { if ("built" in d) this.built = d.built; }

function LoopBench2::Start()
{
	{
		local ex = AIVehicleList();
		if (ex.Count() > 0) { AILog.Info("LB2 RESUME trains=" + ex.Count()); while (true) { this.Report(); this.Sleep(150); } }
	}

	AICompany.SetName("LoopBench2");
	AICompany.SetLoanAmount(AICompany.GetMaxLoanAmount());

	local rts = AIRailTypeList();
	if (rts.Count() == 0) { AILog.Error("no rail"); return; }
	local rt = rts.Begin();
	AIRail.SetCurrentRailType(rt);

	local engine = this.PickEngine(rt);
	if (engine == null) { AILog.Error("no engine"); return; }
	AILog.Info("engine " + AIEngine.GetName(engine));

	// Grid of large rings. SIDE=20 ring, PITCH=28 spacing within the 256 map.
	local SIDE = 20, PITCH = 28, LO = 6, HI = 248;
	local count = 0, placed = 0;
	for (local oy = LO; oy + SIDE + 3 <= HI; oy += PITCH) {
		for (local ox = LO; ox + SIDE + 3 <= HI; ox += PITCH) {
			count += this.BuildRing(ox, oy, SIDE, engine);
			placed++;
		}
	}
	this.total = count;
	this.built = true;
	AILog.Info("LB2 READY n=" + count + " rings=" + placed);
	while (true) { this.Report(); this.Sleep(150); }
}

function LoopBench2::Report()
{
	local vl = AIVehicleList();
	local total = 0, moving = 0, sum = 0, indepot = 0;
	foreach (v, _ in vl) {
		if (AIVehicle.GetVehicleType(v) != AIVehicle.VT_RAIL) continue;
		total++;
		local s = AIVehicle.GetCurrentSpeed(v);
		sum += s; if (s > 0) moving++;
		if (AIVehicle.IsInDepot(v)) indepot++;
	}
	AILog.Info("MOTION total=" + total + " moving=" + moving + " avg=" + (total > 0 ? sum / total : 0) + " indepot=" + indepot);
}

function LoopBench2::PickEngine(rt)
{
	local list = AIEngineList(AIVehicle.VT_RAIL);
	local best = null, bs = -1;
	foreach (e, _ in list) {
		if (!AIEngine.IsValidEngine(e) || AIEngine.IsWagon(e)) continue;
		if (!AIEngine.CanRunOnRail(e, rt) || !AIEngine.HasPowerOnRail(e, rt)) continue;
		local s = AIEngine.GetMaxSpeed(e);
		if (s > bs) { bs = s; best = e; }
	}
	return best;
}

function LoopBench2::BuildRing(ox, oy, S, engine)
{
	local x0 = ox, y0 = oy, x1 = ox + S, y1 = oy + S;
	local T = AIMap.GetTileIndex;

	// Ring as four spans, each running through a corner into the next side.
	AIRail.BuildRail(T(x0 + 1, y0), T(x0, y0), T(x1, y0));
	AIRail.BuildRail(T(x0, y0),     T(x1, y0), T(x1, y1));
	AIRail.BuildRail(T(x1, y0),     T(x1, y1), T(x0, y1));
	AIRail.BuildRail(T(x1, y1),     T(x0, y1), T(x0, y0));
	AIRail.BuildRail(T(x0, y1),     T(x0, y0), T(x1, y0));

	// JUNCTION SIDING off the bottom side: a 3-way point at (jx, y0) with a short
	// dead-end spur going down (-y is outside; go +y into the ring interior is
	// occupied, so spur goes to y0-1 outside the ring). Tap at jx = x0 + S/2 - 2.
	local jx = x0 + (S / 2) - 2;
	// Spur: from ring tile (jx, y0) branch to (jx, y0 - 1) .. dead end. This makes
	// (jx, y0) a tile with two outgoing tracks (east along ring, and north to spur),
	// i.e. a real choice for an eastbound train.
	AIRail.BuildRail(T(jx - 1, y0), T(jx, y0), T(jx, y0 - 1));

	// Waypoints (bottom mid + top mid) for circulating orders.
	local wp_b = T(x0 + (S / 2), y0);
	local wp_t = T(x0 + (S / 2), y1);
	AIRail.BuildRailWaypoint(wp_b);
	AIRail.BuildRailWaypoint(wp_t);

	// One-way PBS signals clockwise, sparse (every 6 tiles).
	this.RingSignals(x0, y0, x1, y1, 6);

	// Inline depot on the LEFT side, opening east onto ring tile (x0, y0+5).
	local ring_tap = T(x0, y0 + 5);
	local depot = T(x0 - 1, y0 + 5);
	AIRail.BuildRailDepot(depot, ring_tap);
	AIRail.BuildRail(T(x0, y0 + 4), ring_tap, T(x0, y0 + 6)); // ensure connectivity along left side

	local t = AIVehicle.BuildVehicle(depot, engine);
	if (!AIVehicle.IsValidVehicle(t)) { AILog.Warning("build fail " + AIError.GetLastErrorString()); return 0; }
	AIOrder.AppendOrder(t, wp_b, AIOrder.OF_NON_STOP_INTERMEDIATE | AIOrder.OF_NON_STOP_DESTINATION);
	AIOrder.AppendOrder(t, wp_t, AIOrder.OF_NON_STOP_INTERMEDIATE | AIOrder.OF_NON_STOP_DESTINATION);
	AIVehicle.StartStopVehicle(t);
	return 1;
}

function LoopBench2::RingSignals(x0, y0, x1, y1, step)
{
	local T = AIMap.GetTileIndex;
	for (local x = x0 + 2; x < x1 - 1; x += step) AIRail.BuildSignal(T(x, y0), T(x + 1, y0), AIRail.SIGNALTYPE_PBS_ONEWAY);
	for (local y = y0 + 2; y < y1 - 1; y += step) AIRail.BuildSignal(T(x1, y), T(x1, y + 1), AIRail.SIGNALTYPE_PBS_ONEWAY);
	for (local x = x1 - 2; x > x0 + 1; x -= step) AIRail.BuildSignal(T(x, y1), T(x - 1, y1), AIRail.SIGNALTYPE_PBS_ONEWAY);
	for (local y = y1 - 2; y > y0 + 1; y -= step) AIRail.BuildSignal(T(x0, y), T(x0, y - 1), AIRail.SIGNALTYPE_PBS_ONEWAY);
}
