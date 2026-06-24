"""Tests for closing the raycaster FSM through the place-and-route pipeline (hdl/raycaster_pipeline.py).

This is the backend-closure suite for the raycaster, mirroring hdl/test_cpu.py: lower the FSM's
combinational cones to the buildable {NOR, CONST0, CONST1} set and prove them correct; build a
registered (DFF + NOR) slice and prove it sequential_equivalent to the behavioural cast over a
frame; route representative slices through the real place_and_route (register tiles + clock spine)
and pin what closes DRC-clean; emit a Scenario/.nut and reconstruct + verify_equivalence.

Checks, in order of trust:

  1. The DDA cast micro-step COMBINATIONAL cone (advance + map test + frac) lowers to the buildable
     set and computes cast_step_reference exactly over the real DDA trajectory for every angle.
  2. The registered (DFF + NOR) ray MARCHER is sequential_equivalent to the behavioural cast over a
     full column of steps (a frame's inner loop), for the high-level and the kept-register-lowered
     forms, and its latched hit equals golden raycaster._cast_hw.
  3. The per-column SHADE cone lowers and computes _slice_top_bot / _wall_shade exactly.
  4. The representative ROUTABLE slices close: the advance cone routes 100 percent of nets DRC-clean
     and emit+reconstruct verify_equivalence; the sequential distance pipeline routes DRC-clean with
     a register tile per bit and the clock reaching every one.
  5. The metrics the brief asks for (NOR cells, register bits, cycles/frame, footprint, route%/DRC)
     are reported and sanity-pinned. The large cones' honest STUCK.md #8 route status is documented.

Run only this file:
    python -m pytest hdl/test_raycaster_pipeline.py -q
"""

from __future__ import annotations

import random

import pytest

from netlist import BUILDABLE, sequential_equivalent, simulate_trace

import raycaster as rc
import raycaster_fsm as F
import raycaster_pipeline as P
from raycaster_pipeline import (
    build_cast_advance_cone_netlist,
    build_cast_march_netlist,
    build_cast_step_cone_netlist,
    build_col_shade_cone_netlist,
    build_dist_pipeline_netlist,
    build_route_slice,
    build_seq_route_slice,
    cast_march_reference,
    cast_step_reference,
    dist_pipeline_reference,
    emit_and_reconstruct_slice,
    march_output_trace,
    route_slice_report,
)


ALL_ANGLES = list(range(rc.NUM_ANGLES))
SWEEP = [0, 3, 7, 12, 17, 24, 30]


# --- 1: the DDA cast micro-step combinational cone is buildable and correct --------

def test_cast_step_cone_builds_and_lowers():
    nl = build_cast_step_cone_netlist()
    nl.validate()
    assert set(nl.ports.outputs) == (
        {f"nx{i}" for i in range(8)} | {f"ny{i}" for i in range(8)}
        | {"solid"} | {f"frac{i}" for i in range(4)})
    low = nl.to_nor()
    assert all(c.type in BUILDABLE for c in low.cells), "cast cone must lower to buildable cells"
    assert low.stats().get("NOR", 0) > 0


def _cone_step(nl, angle, x, y):
    iv = {f"angle{i}": (angle >> i) & 1 for i in range(5)}
    iv.update({f"x{i}": (x >> i) & 1 for i in range(8)})
    iv.update({f"y{i}": (y >> i) & 1 for i in range(8)})
    o = nl.outputs_for(iv)
    return {
        "nx": sum(o[f"nx{i}"] << i for i in range(8)),
        "ny": sum(o[f"ny{i}"] << i for i in range(8)),
        "solid": o["solid"],
        "frac": sum(o[f"frac{i}"] << i for i in range(4)),
    }


def test_cast_step_cone_matches_reference_over_real_trajectories():
    # the cone computes one DDA micro-step exactly as cast_step_reference (the body of
    # golden raycaster._cast_hw), over every position the real ray march visits, for every angle.
    nl = build_cast_step_cone_netlist()
    for angle in ALL_ANGLES:
        x, y = rc.PLAYER_X, rc.PLAYER_Y
        for _ in range(rc.STEPS):
            got = _cone_step(nl, angle, x, y)
            ref = cast_step_reference(angle, x, y)
            assert got == ref, f"cast cone != reference at angle {angle} pos ({x},{y})"
            if ref["solid"]:
                break
            x, y = got["nx"], got["ny"]


def test_nor_lowered_cast_step_cone_matches_reference():
    # the BUILDABLE form computes the same micro-step (the lowering is verified, not assumed),
    # sampled over a few angles' real trajectories.
    low = build_cast_step_cone_netlist().to_nor()
    for angle in (0, 12, 24):
        x, y = rc.PLAYER_X, rc.PLAYER_Y
        for _ in range(rc.STEPS):
            got = _cone_step(low, angle, x, y)
            ref = cast_step_reference(angle, x, y)
            assert got == ref, f"NOR cast cone != reference at angle {angle} pos ({x},{y})"
            if ref["solid"]:
                break
            x, y = got["nx"], got["ny"]


# --- 2: the registered ray marcher is sequential_equivalent over a frame -----------

@pytest.mark.parametrize("angle", SWEEP)
def test_registered_marcher_matches_behavioural_and_lowered(angle):
    # the DFF + NOR marcher steps the DDA one micro-step per clock; over a full column of steps
    # (a frame's inner loop) the high-level netlist, its kept-register lowering, and the Python
    # cast model all produce the identical per-cycle (done, hit_d, hit_f) trace.
    nl = build_cast_march_netlist(angle)
    assert nl.is_sequential()
    assert nl.clocks() == ["clk"]
    low = nl.to_nor(keep_registers=True)
    assert sum(1 for c in low.cells if c.type == "DFF") == \
        sum(1 for c in nl.cells if c.type == "DFF")
    steps = rc.STEPS + 3
    ref = cast_march_reference(angle, steps)
    assert march_output_trace(nl, angle, steps) == ref
    assert march_output_trace(low, angle, steps) == ref


def test_registered_marcher_latched_hit_equals_cast_hw():
    # the marcher's final latched (hit_d, hit_f) equals golden raycaster._cast_hw for every column
    # angle, so the registered slice reproduces the oracle's per-column cast result exactly.
    steps = rc.STEPS + 3
    for angle in ALL_ANGLES:
        trace = march_output_trace(build_cast_march_netlist(angle), angle, steps)
        final = trace[-1]
        hd = sum(final[f"hit_d{i}"] << i for i in range(6))
        hf = sum(final[f"hit_f{i}"] << i for i in range(4))
        cd, cf = rc._cast_hw(rc.PLAYER_X, rc.PLAYER_Y, angle)
        assert (hd, hf) == (cd, cf), f"angle {angle}: marcher hit ({hd},{hf}) != _cast_hw ({cd},{cf})"


def test_registered_marcher_sequential_equivalent_contract():
    # the synth.netlist.sequential_equivalent contract holds between the behavioural marcher and
    # its all-NOR-with-register-tiles lowering over a march schedule (start then steps).
    angle = 12
    nl = build_cast_march_netlist(angle)
    low = nl.to_nor(keep_registers=True)
    steps = rc.STEPS + 3
    trace = [{"start": 1 if k == 0 else 0} for k in range(steps)]
    assert sequential_equivalent(nl, low, trace, clock="clk", skip_cycles=0)


# --- 3: the per-column shade cone lowers and computes the geometry/shade exactly ----

def test_col_shade_cone_matches_reference():
    nl = build_col_shade_cone_netlist()
    nl.validate()
    low = nl.to_nor()
    assert all(c.type in BUILDABLE for c in low.cells)
    for dist in range(1, rc.STEPS + 1):
        top_ref, bot_ref = F._slice_top_bot(dist)
        for frac in range(16):
            for tex in (0, 1):
                iv = {f"dist{i}": (dist >> i) & 1 for i in range(6)}
                iv.update({f"frac{i}": (frac >> i) & 1 for i in range(4)})
                iv["tex"] = tex
                o = nl.outputs_for(iv)
                gtop = sum(o[f"top{i}"] << i for i in range(6))
                gbot = sum(o[f"bot{i}"] << i for i in range(6))
                gsh = sum(o[f"shade{i}"] << i for i in range(5))
                sref = F._wall_shade(dist, frac, bool(tex))
                assert (gtop, gbot, gsh) == (top_ref, bot_ref, sref), \
                    f"shade cone != ref at dist={dist} frac={frac} tex={tex}"


def test_nor_lowered_col_shade_cone_matches_reference():
    low = build_col_shade_cone_netlist().to_nor()
    for dist in range(1, rc.STEPS + 1):
        top_ref, bot_ref = F._slice_top_bot(dist)
        for frac in (0, 5, 10, 15):
            for tex in (0, 1):
                iv = {f"dist{i}": (dist >> i) & 1 for i in range(6)}
                iv.update({f"frac{i}": (frac >> i) & 1 for i in range(4)})
                iv["tex"] = tex
                o = low.outputs_for(iv)
                gtop = sum(o[f"top{i}"] << i for i in range(6))
                gbot = sum(o[f"bot{i}"] << i for i in range(6))
                gsh = sum(o[f"shade{i}"] << i for i in range(5))
                assert (gtop, gbot, gsh) == (top_ref, bot_ref, F._wall_shade(dist, frac, bool(tex)))


# --- 4: the representative routable slices close (route 100 percent, DRC-clean) ----

def test_advance_slice_routes_drc_clean_and_reconstructs():
    # the clean combinational slice (the dual-axis DDA advance) places + channel-routes 100 percent
    # of nets with 0 DRC violations, and the placement reconstructs to an equivalent netlist.
    clean = build_route_slice(12)
    assert all(c.type in BUILDABLE for c in clean.cells)
    rep = route_slice_report(clean)
    assert rep["overlaps"] == 0
    assert rep["unrouted"] == 0
    assert rep["routed"] == rep["total_nets"] > 0
    assert rep["drc_violations"] == 0, f"DRC: {rep['drc_kinds']}"

    er = emit_and_reconstruct_slice(clean)
    assert er["equivalent"] is True
    assert "GetScenarioData" in er["nut"]


def test_advance_cone_advance_only_is_the_clean_slice():
    # the advance cone with and without the frac pick both route DRC-clean now that the router
    # reserves an output-pad channel (the with_frac form used to trip the shared router's edge-pad
    # fallback). Both compute the advance bits identically; this pins that the advance is unchanged.
    plain = build_cast_advance_cone_netlist(12, with_frac=False)
    full = build_cast_advance_cone_netlist(12, with_frac=True)
    assert set(plain.ports.outputs) == {f"nx{i}" for i in range(8)} | {f"ny{i}" for i in range(8)}
    assert {f"frac{i}" for i in range(4)} <= set(full.ports.outputs)
    # the advance bits agree on the player start position.
    iv = {f"x{i}": (rc.PLAYER_X >> i) & 1 for i in range(8)}
    iv.update({f"y{i}": (rc.PLAYER_Y >> i) & 1 for i in range(8)})
    op, ofu = plain.outputs_for(iv), full.outputs_for(iv)
    for i in range(8):
        assert op[f"nx{i}"] == ofu[f"nx{i}"] and op[f"ny{i}"] == ofu[f"ny{i}"]


def test_sequential_dist_pipeline_routes_with_register_tiles_and_clock():
    # the sequential distance pipeline places with one register tile per bit, routes 100 percent of
    # nets DRC-clean, and the clock-distribution spine reaches every register's clock pin.
    low = build_seq_route_slice(4)
    assert low.is_sequential()
    rep = route_slice_report(low)
    assert rep["overlaps"] == 0
    assert rep["unrouted"] == 0
    assert rep["routed"] == rep["total_nets"] > 0
    assert rep["drc_violations"] == 0, f"DRC: {rep['drc_kinds']}"
    assert rep["register_tiles"] == 4 * 6 == 24

    scen = rep["scenario"]
    regs = [c for c in scen.cells if c.is_register()]
    routes = {rt.net: set(rt.path) for rt in scen.routes}
    by_clk = {}
    for r in regs:
        assert r.clock is not None
        by_clk.setdefault(r.clock.net, []).append((r.clock.x, r.clock.y))
    for clk_net, pins in by_clk.items():
        assert clk_net in routes, f"clock net {clk_net} has no spine"
        for px, py in pins:
            assert (px, py) in routes[clk_net], f"clock spine misses pin {(px, py)}"


def test_dist_pipeline_reconstructs_and_steps_identically():
    # the reconstruction-from-placement steps cycle-for-cycle identically to the source under SeqSim
    # (the meaningful sequential check, the analogue of test_cpu's reconstruction-emits-Fibonacci).
    # The full 24-register pipeline's combinational CONE has 31 cut-register inputs, far too wide to
    # enumerate a truth table, so the cone-equivalence truth-table check is done on a narrow pipeline
    # in test_narrow_pipeline_combinational_cone_equivalence; here we use the strong SeqSim sample.
    from check import scenario_to_netlist
    from netlist import SeqSim
    from emit import build_scenario

    low = build_seq_route_slice(4)
    scen, _ = build_scenario(low)
    rebuilt = scenario_to_netlist(scen, require_routed=True)
    assert rebuilt.is_sequential()
    assert sum(1 for c in rebuilt.cells if c.type == "DFF") == 24

    sa, sb = SeqSim(low), SeqSim(rebuilt)
    sa.reset({"clk": 0, "dist0": 0})
    sb.reset({"clk": 0, "dist0": 0})
    rng = random.Random(99)
    for _ in range(30):
        data = {f"dist{i}": rng.randint(0, 1) for i in range(6)}
        sa.clock_cycle(data, clock="clk")
        sb.clock_cycle(data, clock="clk")
        assert [sa.value(f"dout{i}") for i in range(6)] == [sb.value(f"dout{i}") for i in range(6)]


def test_narrow_pipeline_combinational_cone_equivalence():
    # the combinational-cone truth-table equivalence the brief asks for (registers cut, the cone is
    # acyclic), on a NARROW pipeline whose cone is small enough to enumerate: a 2-stage 1-bit delay
    # line (2 registers, cone = clk + din + 2 cut-register inputs). Pins that the placement preserved
    # the next-state logic exactly, complementing the wide pipeline's SeqSim sample above.
    from check import scenario_to_netlist
    from netlist import NetlistBuilder, equivalent
    from emit import build_scenario

    b = NetlistBuilder("narrow_pipe")
    clk = b.declare_input("clk")
    din = b.declare_input("din")
    q0 = b.dff(din, clk)
    q1 = b.dff(q0, clk)
    b.alias_output("dout", q1)
    low = b.finish().to_nor(keep_registers=True)
    scen, _ = build_scenario(low)
    rebuilt = scenario_to_netlist(scen, require_routed=True)
    assert equivalent(low.combinational_cone(), rebuilt.combinational_cone())


def test_dist_pipeline_reference_matches_lowered():
    # the lowered pipeline reproduces the plain Python delay-line reference (under the clock_cycle
    # latency convention), so the registered slice is a verified circuit, not a faked delay.
    low = build_dist_pipeline_netlist(4).to_nor(keep_registers=True)
    rng = random.Random(5)
    vals = [rng.randint(0, 48) for _ in range(40)]
    trace = [{f"dist{i}": (v >> i) & 1 for i in range(6)} for v in vals]
    got = simulate_trace(low, trace, clock="clk")
    got_vals = [sum(g[f"dout{i}"] << i for i in range(6)) for g in got]
    assert got_vals == dist_pipeline_reference(4, vals)


# --- 5: the metrics the brief asks for (reported, sanity-pinned) -------------------

def test_fsm_metrics_reported():
    m = P.fsm_metrics()
    assert m["control_register_bits"] == 84      # the lean control/datapath state budget
    assert m["framebuffer_bits"] == F.W * F.H == 2048
    # the combinational cones lower to real, non-trivial NOR cones.
    assert m["paint_cone_NOR"] > 500
    assert m["cast_cone_NOR"] > 500
    assert m["shade_cone_NOR"] > 500
    print("raycaster FSM metrics:", m)


def test_cycles_per_frame_reported():
    cyc = P.cycles_per_frame(0)
    assert 0 < cyc < 100000
    print("raycaster FSM cycles/frame (heading 0):", cyc)


def test_larger_cone_routes_all_nets_drc_clean():
    # Previously the HONEST NEGATIVE (STUCK.md #8): the ~484-NOR advance+frac cone routed every net
    # but tripped a route_cuts_pad + route_short because its 20 output pads, stacked one-per-row in a
    # single right-edge column, exhausted the few free columns west of them and pushed later pad
    # risers east of the pad column, where they cut the neighbouring pads. The router now reserves an
    # output-pad channel (two columns per pad plus slack) west of the pad column, the mirror of the
    # input-side left margin, so every pad riser lands in clear space. With that and the wide-fan-in
    # footprint/coalesce fixes, this cone routes 100 percent of nets DRC-clean, like the adder, the
    # ALU, the CPU, and the ~1419-NOR paint cone (all 0 DRC through the same shared router).
    low = build_cast_advance_cone_netlist(12, with_frac=True).to_nor()
    rep = route_slice_report(low)
    assert rep["routed"] == rep["total_nets"], "every net must still route"
    assert rep["unrouted"] == 0
    assert rep["drc_violations"] == 0, f"DRC: {rep['drc_kinds']}"
    print("advance+frac cone route status:", rep["routed"], "/", rep["total_nets"],
          "nets, DRC", rep["drc_violations"], rep["drc_kinds"])
