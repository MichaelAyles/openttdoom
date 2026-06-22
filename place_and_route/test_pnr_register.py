"""Tests for SEQUENTIAL place-and-route: register tiles plus the clock-distribution net.

This is the sequential extension of test_pnr.py. The combinational backend places NOR cells
and routes data nets; here we add the clocked REGISTER tile (a DFF) and the CLOCK net that must
reach every register. The checks mirror the combinational ones and add the sequential pieces:

  1. A sequential netlist (toggle flip-flop, shift register, free-running counter) PLACES, with
     each register a distinct register tile (bigger footprint, a clock pin off the data pins).
  2. It ROUTES to 100 percent of nets with 0 DRC violations, the same constructive channel
     router and perpendicular-bridge rule as the combinational path.
  3. The CLOCK-DISTRIBUTION net physically reaches EVERY register's clock pin: the clock net's
     trunk row is the clock spine, with a riser dropping onto each register tile's clock pin.
  4. The scenario RECONSTRUCTS to a sequential netlist that steps cycle-for-cycle identically to
     the source under SeqSim (the meaningful sequential-equivalence), and whose COMBINATIONAL
     CONE (registers cut) is equivalent() to the source cone (the truth-table check the brief
     asks for, valid because the cone is acyclic).
  5. The scenario emits a Scenario/.nut and round-trips through JSON unchanged.

The clock tree is intentionally a single SPINE per clock net (one unique trunk row fanning to
every register via risers), documented honestly: it is not a buffered H-tree, just the router's
existing trunk+riser fan-out applied to the clock net. That is sufficient for the substrate
model (the clock is a train on a fixed loop sampled once per lap, scenarios/gate_model.py), and
it crosses other nets only as legal perpendicular bridges, so no clock-specific routing rule is
needed. See place.REG_W/REG_H for the honest register-footprint reservation (the in-tile track
geometry of a register is TODO(human), tracked in STUCK.md, exactly as the combinational NOR
geometry was before it was solved).

Run just this file:  python -m pytest place_and_route/test_pnr_register.py -q
"""

from __future__ import annotations

import json
import os
import random

from netlist import Netlist, NetlistBuilder, SeqSim, equivalent
from scenario import Scenario
from emit import build_scenario
from check import (drc, overlap_violations, scenario_to_netlist,
                   verify_equivalence, unrouted_nets)

# The toggle flip-flop and the up-counter come straight from the sequential SYNTH work
# (hdl/sequential.py), so this place-and-route test runs the SAME register netlists the synth
# track verified, end to end onto a placed/routed scenario. The shift register is local (it is
# not in that module) and exercises a clock fanning to a chain of registers with no feedback.
from sequential import build_toggle_ff, build_counter


def build_toggle() -> Netlist:
    """The toggle flip-flop from the synth work: q = DFF(NOT q, clk). One register."""
    return build_toggle_ff()


def build_shift(n: int = 4) -> Netlist:
    """An n-stage shift register: din -> q0 -> q1 -> ... on one shared clock (n registers)."""
    b = NetlistBuilder(f"shift{n}")
    din = b.declare_input("din")
    clk = b.declare_input("clk")
    prev = din
    for i in range(n):
        prev = b.dff(prev, clk)
        b.alias_output(f"q{i}", prev)
    return b.finish()


# --- helper: full sequential place-and-route assertion ---------------------------

def _assert_sequential_complete(nl: Netlist):
    """Lower (keep registers), place + route, and assert the sequential design closes:

      - every net routed (100 percent), 0 DRC violations, no overlaps,
      - the clock net reaches every register tile's clock pin,
      - the reconstruction steps cycle-for-cycle identically (sequential equivalence) and its
        combinational cone is equivalent() to the source cone.

    Returns (low, scen, rr) for further per-test assertions.
    """
    low = nl.to_nor(keep_registers=True)
    assert low.is_sequential(), "lowered sequential netlist must keep its register tiles"
    # every register survived lowering as a single DFF cell (not expanded to latches).
    assert sum(1 for c in low.cells if c.type == "DFF") == \
        sum(1 for c in nl.cells if c.type == "DFF")
    for c in low.cells:
        assert c.type in ("NOR", "CONST0", "CONST1", "DFF"), \
            f"unexpected non-buildable cell {c.id}:{c.type} after keep-register lowering"

    scen, rr = build_scenario(low)

    # placement legal, routing complete, DRC clean.
    assert overlap_violations(scen) == []
    assert drc(scen) == [], f"DRC: {[(v.kind, v.detail) for v in drc(scen)]}"
    assert unrouted_nets(scen) == [], f"unrouted: {unrouted_nets(scen)}"
    routed, total = rr.coverage()
    assert routed == total, f"routed only {routed}/{total}"

    # register tiles present and the clock reaches every one of them.
    regs = [c for c in scen.cells if c.is_register()]
    assert len(regs) == sum(1 for c in low.cells if c.type == "DFF") > 0
    _assert_clock_reaches_every_register(scen, regs)

    # reconstruction: same registers, steps identically, comb-cone equivalent.
    rebuilt = scenario_to_netlist(scen, require_routed=True)
    assert rebuilt.is_sequential()
    assert sum(1 for c in rebuilt.cells if c.type == "DFF") == len(regs)
    assert equivalent(low.combinational_cone(), rebuilt.combinational_cone()), \
        "reconstructed combinational cone must equal the source cone"

    return low, scen, rr


def _assert_clock_reaches_every_register(scen: Scenario, regs):
    """The clock-distribution net's route must physically touch every register's clock pin."""
    # group register clock pins by their clock net, then check each net's route covers them.
    by_clk = {}
    for r in regs:
        assert r.clock is not None, f"register {r.id} has no clock pin"
        by_clk.setdefault(r.clock.net, []).append((r.clock.x, r.clock.y))
    routes = {rt.net: set(rt.path) for rt in scen.routes}
    for clk_net, pins in by_clk.items():
        assert clk_net in routes, f"clock net {clk_net} has no route (no spine)"
        spine = routes[clk_net]
        for px, py in pins:
            assert (px, py) in spine, \
                f"clock {clk_net} spine does not reach register clock pin {(px, py)}"


# --- 1: each design places + routes completely with a reaching clock --------------

def test_toggle_flip_flop_places_routes_with_clock():
    _assert_sequential_complete(build_toggle())


def test_shift_register_places_routes_with_clock():
    low, scen, rr = _assert_sequential_complete(build_shift(4))
    # the one clock net fans out to all four register tiles off a single spine.
    regs = [c for c in scen.cells if c.is_register()]
    assert len(regs) == 4
    clk_pins = {(r.clock.x, r.clock.y) for r in regs}
    assert len(clk_pins) == 4, "each register must have its own distinct clock pin tile"


def test_counter_places_routes_with_clock():
    # The counter combines a next-state cone, register feedback, and a clock fanning to every
    # register, so it exercises the whole sequential path at once.
    low, scen, rr = _assert_sequential_complete(build_counter(3))
    regs = [c for c in scen.cells if c.is_register()]
    assert len(regs) == 3
    # a real design with feedback is not planar, so it uses bridge crossings.
    assert sum(len(r.bridges) for r in scen.routes) > 0


# --- 2: the clock spine is a single trunk row fanning to risers -------------------

def test_clock_net_is_one_spine_fanning_to_every_register():
    low = build_shift(3).to_nor(keep_registers=True)
    scen, rr = build_scenario(low)
    clk_routes = [r for r in scen.routes if r.net == "clk"]
    assert len(clk_routes) == 1, "the clock-distribution net is one route (one spine)"
    regs = [c for c in scen.cells if c.is_register()]
    spine = set(clk_routes[0].path)
    # the spine touches the clock source pad AND every register clock pin.
    clk_pad = [p for p in scen.io if p.net == "clk"]
    assert clk_pad, "clock net should have a source pad (it is a primary input here)"
    assert (clk_pad[0].x, clk_pad[0].y) in spine
    for r in regs:
        assert (r.clock.x, r.clock.y) in spine


# --- 3: sequential equivalence under SeqSim (the meaningful behavioural check) -----

def test_reconstructed_shift_register_steps_identically():
    nl = build_shift(4)
    low = nl.to_nor(keep_registers=True)
    scen, _ = build_scenario(low)
    rebuilt = scenario_to_netlist(scen, require_routed=True)

    simA, simB = SeqSim(low), SeqSim(rebuilt)
    simA.reset({"din": 0, "clk": 0})
    simB.reset({"din": 0, "clk": 0})
    rng = random.Random(2025)
    outs = [f"q{i}" for i in range(4)]
    for _ in range(40):
        v = rng.randint(0, 1)
        simA.clock_cycle({"din": v}, clock="clk")
        simB.clock_cycle({"din": v}, clock="clk")
        assert [simA.value(o) for o in outs] == [simB.value(o) for o in outs]


def test_reconstructed_counter_counts_identically():
    nl = build_counter(3)
    low = nl.to_nor(keep_registers=True)
    scen, _ = build_scenario(low)
    rebuilt = scenario_to_netlist(scen, require_routed=True)

    simA, simB = SeqSim(low), SeqSim(rebuilt)
    simA.reset({"clk": 0, "en": 0})
    simB.reset({"clk": 0, "en": 0})
    seq = []
    for _ in range(10):
        simA.clock_cycle({"en": 1}, clock="clk")   # enable high: count up each edge
        simB.clock_cycle({"en": 1}, clock="clk")
        va = sum(simA.value(f"q{i}") << i for i in range(3))
        vb = sum(simB.value(f"q{i}") << i for i in range(3))
        assert va == vb
        seq.append(va)
    # the reconstructed placement counts the same 0..7 wrap as the source (offset by reset flush).
    assert seq == [1, 2, 3, 4, 5, 6, 7, 0, 1, 2]


# --- 4: combinational-cone equivalence (truth-table check around the registers) ----

def test_combinational_cone_equivalence_after_place_and_route():
    for nl in (build_toggle(), build_shift(4), build_counter(3)):
        low = nl.to_nor(keep_registers=True)
        scen, _ = build_scenario(low)
        assert verify_equivalence_sequential(low, scen), \
            f"cone equivalence failed for {nl.name}"


def verify_equivalence_sequential(source: Netlist, scen: Scenario) -> bool:
    """Reconstruct the scenario and compare combinational cones (registers cut)."""
    rebuilt = scenario_to_netlist(scen, require_routed=True)
    return equivalent(source.combinational_cone(), rebuilt.combinational_cone())


# --- 5: emit + JSON round trip ----------------------------------------------------

def test_sequential_scenario_json_round_trip():
    low = build_counter(3).to_nor(keep_registers=True)
    scen, _ = build_scenario(low)
    blob = scen.to_json()
    scen2 = Scenario.from_dict(json.loads(blob))

    # register fields (clock pin, reset) survive the round trip.
    regs1 = {c.id: c for c in scen.cells if c.is_register()}
    regs2 = {c.id: c for c in scen2.cells if c.is_register()}
    assert set(regs1) == set(regs2)
    for cid in regs1:
        a, b = regs1[cid], regs2[cid]
        assert a.clock.net == b.clock.net
        assert (a.clock.x, a.clock.y) == (b.clock.x, b.clock.y)
        assert a.reset == b.reset

    # the reloaded scenario still passes DRC and reconstructs to the same logic.
    assert drc(scen2) == []
    assert equivalent(low.combinational_cone(),
                      scenario_to_netlist(scen2, require_routed=True).combinational_cone())


def test_sequential_nut_emits_clock_and_registers():
    low = build_shift(3).to_nor(keep_registers=True)
    scen, _ = build_scenario(low)
    nut = scen.to_nut()
    assert "GetScenarioData" in nut
    # the .nut carries the register clock pins (a clock= field on the register cells).
    assert "clock=" in nut
    # and a DFF cell type appears (the register tile).
    assert 'type="DFF"' in nut


# --- 6: backward compatibility (combinational path unchanged) ---------------------

def test_old_placedcell_json_without_register_fields_loads():
    """A scenario cell JSON written before registers existed (no clock/reset keys) still loads,
    with clock None and reset 0 (a combinational cell)."""
    old = {
        "name": "old",
        "cells": [{"id": "g0", "type": "NOR", "x": 1, "y": 1, "w": 14, "h": 3,
                   "inputs": [{"net": "a", "x": 1, "y": 2}],
                   "output": {"net": "y", "x": 13, "y": 2}}],
        "routes": [], "io": [], "framebuffer": None,
    }
    scen = Scenario.from_dict(old)
    assert scen.cells[0].clock is None
    assert scen.cells[0].reset == 0
    assert not scen.cells[0].is_register()


def test_write_example_sequential_scenario():
    """Emit the canonical sequential example (the 3-bit counter) to scenarios/ as JSON and .nut,
    and confirm it loads back, passes DRC, and reconstructs to the source logic. This doubles as
    the saved sequential artifact alongside the combinational example.scenario.json."""
    low = build_counter(3).to_nor(keep_registers=True)
    scen, rr = build_scenario(low)

    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "scenarios")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "counter3.scenario.json")
    nut_path = os.path.join(out_dir, "counter3.scenario.nut")

    scen.save(json_path)
    with open(nut_path, "w") as f:
        f.write(scen.to_nut())

    assert os.path.exists(json_path) and os.path.exists(nut_path)
    reloaded = Scenario.load(json_path)
    assert drc(reloaded) == []
    assert [c for c in reloaded.cells if c.is_register()], "saved scenario must have registers"
    assert equivalent(low.combinational_cone(),
                      scenario_to_netlist(reloaded, require_routed=True).combinational_cone())
    with open(nut_path) as f:
        nut = f.read()
    assert "GetScenarioData" in nut and 'type="DFF"' in nut


def test_combinational_netlist_still_has_no_registers():
    """A purely combinational netlist places with NO register tiles and an empty clock set, so
    the sequential extension does not perturb the combinational path."""
    b = NetlistBuilder("comb")
    a = b.declare_input("a")
    bb = b.declare_input("b")
    b.alias_output("y", b.nor([a, bb]))
    nl = b.finish()
    assert nl.clocks() == []
    scen, _ = build_scenario(nl)
    assert [c for c in scen.cells if c.is_register()] == []
    assert verify_equivalence(nl, scen, require_routed=True) is True
