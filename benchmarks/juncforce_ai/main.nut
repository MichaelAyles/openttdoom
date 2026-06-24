/*
 * JuncForce: build rings that FORCE the per-train YAPF to run every lap.
 *
 * The OpenTTD reservation follower (ExtendTrainReservation) only hands off to the
 * YAPF A* search when it reaches a tile with MORE THAN ONE onward trackdir (a real
 * fork) before it finds a safe waiting position (a PBS signal or a track end). So to
 * make YAPF fire we build a ring with a TWO-WAY junction and put the ONLY PBS signal
 * far enough back that, after the train passes it, it meets the fork before the next
 * safe tile. At the fork the train must choose; YAPF chooses "stay on the ring" every
 * lap (the waypoint is on the ring), which is the recomputed constant the cache cuts.
 *
 * Topology per unit: a rectangular ring. On the bottom side, a diagonal CHORD cuts
 * across one corner, creating a junction at (jx, y0): going east the train can either
 * continue along the bottom OR take the chord. We deliberately keep the bottom side
 * signal-free between the left-side signal and the junction so the follower hits the
 * fork without a safe tile in between.
 */

class JuncForce extends AIController { built = false; total = 0; }
function JuncForce::Save() { return { built = this.built }; }
function JuncForce::Load(v, d) { if ("built" in d) this.built = d.built; }

function JuncForce::Start()
{
	{ local ex = AIVehicleList(); if (ex.Count() > 0) { AILog.Info("JF RESUME " + ex.Count()); while (true) { this.Report(); this.Sleep(150); } } }
	AICompany.SetName("JuncForce");
	AICompany.SetLoanAmount(AICompany.GetMaxLoanAmount());
	local rts = AIRailTypeList(); if (rts.Count() == 0) { AILog.Error("no rail"); return; }
	local rt = rts.Begin(); AIRail.SetCurrentRailType(rt);
	local engine = this.PickEngine(rt); if (engine == null) { AILog.Error("no engine"); return; }

	local SIDE = 18, PITCH = 26, LO = 6, HI = 248;
	local count = 0, placed = 0;
	for (local oy = LO; oy + SIDE + 3 <= HI; oy += PITCH) {
		for (local ox = LO; ox + SIDE + 3 <= HI; ox += PITCH) {
			count += this.BuildRing(ox, oy, SIDE, engine); placed++;
		}
	}
	this.total = count; this.built = true;
	AILog.Info("JF READY n=" + count + " rings=" + placed);
	while (true) { this.Report(); this.Sleep(150); }
}

function JuncForce::Report()
{
	local vl = AIVehicleList(); local total = 0, moving = 0, sum = 0;
	foreach (v, _ in vl) { if (AIVehicle.GetVehicleType(v) != AIVehicle.VT_RAIL) continue; total++; local s = AIVehicle.GetCurrentSpeed(v); sum += s; if (s > 0) moving++; }
	AILog.Info("MOTION total=" + total + " moving=" + moving + " avg=" + (total > 0 ? sum / total : 0));
}

function JuncForce::PickEngine(rt)
{
	local list = AIEngineList(AIVehicle.VT_RAIL); local best = null, bs = -1;
	foreach (e, _ in list) {
		if (!AIEngine.IsValidEngine(e) || AIEngine.IsWagon(e)) continue;
		if (!AIEngine.CanRunOnRail(e, rt) || !AIEngine.HasPowerOnRail(e, rt)) continue;
		local s = AIEngine.GetMaxSpeed(e); if (s > bs) { bs = s; best = e; }
	}
	return best;
}

function JuncForce::BuildRing(ox, oy, S, engine)
{
	local x0 = ox, y0 = oy, x1 = ox + S, y1 = oy + S;
	local T = AIMap.GetTileIndex;

	// Ring.
	AIRail.BuildRail(T(x0 + 1, y0), T(x0, y0), T(x1, y0));
	AIRail.BuildRail(T(x0, y0),     T(x1, y0), T(x1, y1));
	AIRail.BuildRail(T(x1, y0),     T(x1, y1), T(x0, y1));
	AIRail.BuildRail(T(x1, y1),     T(x0, y1), T(x0, y0));
	AIRail.BuildRail(T(x0, y1),     T(x0, y0), T(x1, y0));

	// CHORD across the bottom-right corner: from a junction (jx,y0) on the bottom
	// side, run a diagonal-ish shortcut up to (x1, jy) on the right side, rejoining
	// the ring. This makes (jx,y0) a fork (continue east along bottom, or take chord
	// north-east) and (x1,jy) a merge.
	local jx = x0 + S - 5;   // fork near bottom-right
	local jy = y0 + 5;       // merge on right side
	// Build chord: (jx,y0) -> (jx+2, y0) curve into vertical -> up to (jx+2, jy) -> into (x1,jy).
	AIRail.BuildRail(T(jx - 1, y0), T(jx, y0), T(jx + 2, y0));      // along bottom into chord start
	AIRail.BuildRail(T(jx, y0),     T(jx + 2, y0), T(jx + 2, jy));  // up
	AIRail.BuildRail(T(jx + 2, y0), T(jx + 2, jy), T(x1, jy));      // into right side merge

	local wp_b = T(x0 + 3, y0);          // waypoint on bottom BEFORE the fork
	local wp_t = T(x0 + (S / 2), y1);    // waypoint on top
	AIRail.BuildRailWaypoint(wp_b);
	AIRail.BuildRailWaypoint(wp_t);

	// Sparse one-way PBS signals, but DELIBERATELY leave the bottom side between the
	// left side and the fork signal-free, so the follower meets the fork first.
	// Signals: one on left side, one on right side after merge, one on top.
	AIRail.BuildSignal(T(x0, y0 + 3), T(x0, y0 + 4), AIRail.SIGNALTYPE_PBS_ONEWAY);   // left, up
	AIRail.BuildSignal(T(x1, jy + 3), T(x1, jy + 4), AIRail.SIGNALTYPE_PBS_ONEWAY);   // right after merge, up
	AIRail.BuildSignal(T(x0 + (S / 2), y1), T(x0 + (S / 2) - 1, y1), AIRail.SIGNALTYPE_PBS_ONEWAY); // top, west

	// Inline depot on left side opening east.
	local ring_tap = T(x0, y0 + 8);
	local depot = T(x0 - 1, y0 + 8);
	AIRail.BuildRailDepot(depot, ring_tap);

	local t = AIVehicle.BuildVehicle(depot, engine);
	if (!AIVehicle.IsValidVehicle(t)) { AILog.Warning("build fail " + AIError.GetLastErrorString()); return 0; }
	AIOrder.AppendOrder(t, wp_b, AIOrder.OF_NON_STOP_INTERMEDIATE | AIOrder.OF_NON_STOP_DESTINATION);
	AIOrder.AppendOrder(t, wp_t, AIOrder.OF_NON_STOP_INTERMEDIATE | AIOrder.OF_NON_STOP_DESTINATION);
	AIVehicle.StartStopVehicle(t);
	return 1;
}
