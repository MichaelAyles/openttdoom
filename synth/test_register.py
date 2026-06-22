"""Tests for the REGISTER CELL: the clocked 1-bit memory primitive (a D flip-flop).

This is the keystone the CPU datapath and the raycaster FSM depend on, so it is tested
hard. The register is added to synth/netlist.py as the sequential CELL_LIBRARY type DFF,
lowered to an all-NOR master-slave latch by to_nor(), and stepped over clock cycles by the
SeqSim sequential simulator. The checks, in order of trust:

  1. The behavioural DFF holds its value across cycles and updates only on the rising edge.
  2. The all-NOR lowering (cross-coupled NOR master-slave) reproduces the DFF behaviour,
     so the buildable {NOR, CONST0, CONST1} netlist computes the same register.
  3. The one-edge latency matches scenarios/gate_model.py: a registered NOR built from a DFF
     reproduces gate_model.NorTile cycle for cycle.
  4. The combinational simulate()/truth_table() path is unchanged and rejects sequential
     netlists cleanly.
  5. Structural sanity: feedback registers (a toggle flip-flop), a shift-register chain, and
     JSON round-tripping of the sequential fields.

Run only this file:
    python -m pytest synth/test_register.py -q
"""

from __future__ import annotations

import json
import random
from itertools import product

import pytest

from netlist import (
    BUILDABLE,
    SEQUENTIAL,
    Cell,
    Netlist,
    NetlistBuilder,
    Ports,
    SeqSim,
    is_sequential,
    sequential_equivalent,
    simulate_trace,
)
from gate_model import nor as gm_nor, single_nor


# --- shared builders --------------------------------------------------------------

def build_dff() -> Netlist:
    """A single positive-edge DFF: q = DFF(d, clk), output port q."""
    b = NetlistBuilder("dff1")
    d = b.declare_input("d")
    clk = b.declare_input("clk")
    q = b.dff(d, clk)
    b.alias_output("q", q)
    return b.finish()


def build_toggle() -> Netlist:
    """A T (toggle) flip-flop via feedback: q = DFF(NOT q, clk). Divides clk by 2."""
    cells = [
        Cell("inv", "NOT", ["q"], "nq"),
        Cell("ff", "DFF", ["nq"], "q", clock="clk"),
    ]
    return Netlist("toggle", cells, Ports(["clk"], ["q"]))


def build_shift(n: int = 4) -> Netlist:
    """An n-stage shift register: din -> q0 -> q1 -> ... on one shared clock."""
    b = NetlistBuilder("shift")
    din = b.declare_input("din")
    clk = b.declare_input("clk")
    prev = din
    for i in range(n):
        prev = b.dff(prev, clk)
        b.alias_output(f"q{i}", prev)
    return b.finish()


def build_registered_nor() -> Netlist:
    """A clocked NOR tile: y = DFF(NOR(a, b), clk). This is gate_model.NorTile in netlist form
    (a NOR with exactly one edge of register latency)."""
    b = NetlistBuilder("rnor")
    a = b.declare_input("a")
    bb = b.declare_input("b")
    clk = b.declare_input("clk")
    n = b.nor([a, bb])
    q = b.dff(n, clk)
    b.alias_output("y", q)
    return b.finish()


# --- 0: the cell type is registered as sequential ---------------------------------

def test_dff_is_in_library_and_sequential():
    assert "DFF" in SEQUENTIAL
    assert is_sequential("DFF")
    assert not is_sequential("NOR")
    nl = build_dff()
    assert nl.is_sequential()
    ff = [c for c in nl.cells if c.type == "DFF"]
    assert len(ff) == 1
    assert ff[0].clock == "clk"
    assert len(ff[0].inputs) == 1          # exactly one data input D
    assert ff[0].inputs[0] == "d"          # which is the primary input d


# --- 1: the behavioural DFF holds and updates on the edge -------------------------

def test_dff_captures_on_rising_edge():
    nl = build_dff()
    sim = SeqSim(nl)
    sim.reset({"d": 0, "clk": 0})
    schedule = [1, 1, 0, 1, 0, 0, 1, 0]
    got = []
    for v in schedule:
        sim.clock_cycle({"d": v}, clock="clk")
        got.append(sim.value("q"))
    # q after cycle N is exactly the data clocked in on cycle N (one register, no chain).
    assert got == schedule


def test_dff_holds_value_without_an_edge():
    """Changing d with no clock edge must NOT change q: a register holds."""
    nl = build_dff()
    sim = SeqSim(nl)
    sim.reset({"d": 0, "clk": 0})
    sim.clock_cycle({"d": 1}, clock="clk")
    assert sim.value("q") == 1
    # poke d around with the clock high (no fresh rising edge): q must hold 1.
    for v in (0, 1, 0, 0, 1):
        sim.set_inputs({"d": v})
        sim.settle()
        assert sim.value("q") == 1, f"q changed without an edge (d={v})"
    # one real cycle clocking 0 in flips it.
    sim.clock_cycle({"d": 0}, clock="clk")
    assert sim.value("q") == 0


def test_dff_holds_across_many_idle_edges_when_data_stable():
    nl = build_dff()
    sim = SeqSim(nl)
    sim.reset({"d": 0, "clk": 0})
    sim.clock_cycle({"d": 1}, clock="clk")
    for _ in range(8):
        sim.clock_cycle({"d": 1}, clock="clk")
        assert sim.value("q") == 1


def test_dff_reset_value_respected():
    """The behavioural DFF starts at its reset value before any capturing edge."""
    cells_hi = [Cell("ff", "DFF", ["d"], "q", clock="clk", reset=1)]
    nl = Netlist("dffr", cells_hi, Ports(["d", "clk"], ["q"]))
    sim = SeqSim(nl)
    sim.reset({"d": 0, "clk": 0})
    assert sim.value("q") == 1            # reset=1 before any edge
    sim.clock_cycle({"d": 0}, clock="clk")
    assert sim.value("q") == 0            # first edge clocks the data in


# --- 2: the all-NOR lowering reproduces the DFF -----------------------------------

def test_dff_lowers_to_buildable_nor_only():
    nl = build_dff()
    low = nl.to_nor()
    assert low.is_sequential() is False        # no DFF cells survive the lowering
    for c in low.cells:
        assert c.type in BUILDABLE, f"lowered cell {c.id} is non-buildable {c.type}"
    # the lowered register still has the right ports.
    assert set(low.ports.inputs) == {"d", "clk"}
    assert low.ports.outputs == ["q"]


def test_keep_registers_lowering_keeps_dff_tiles_and_lowers_logic():
    """to_nor(keep_registers=True) is the place-and-route lowering: combinational gates become
    NOR but each register stays a single DFF tile (so the placer can stamp a register footprint
    and route a clock to it). Verified on the toggle (feedback) and the shift register (chain)."""
    for nl, ndff in ((build_toggle(), 1), (build_shift(4), 4)):
        low = nl.to_nor(keep_registers=True)
        assert low.is_sequential(), "registers must survive as DFF cells"
        assert sum(1 for c in low.cells if c.type == "DFF") == ndff
        for c in low.cells:
            assert c.type in (BUILDABLE | {"DFF"}), \
                f"keep-register lowering left a non-buildable {c.type}"
        # the DFFs still carry a driven clock net (the placer routes it).
        assert low.clocks() == ["clk"]


def test_keep_registers_lowering_steps_like_full_expansion():
    """The keep-register lowering and the full all-NOR latch expansion compute the SAME register
    behaviour, so choosing to keep register tiles for placement does not change the logic."""
    nl = build_shift(4)
    keep = nl.to_nor(keep_registers=True)   # DFF tiles + NOR logic
    full = nl.to_nor()                       # everything expanded to NOR latches
    simK, simF = SeqSim(keep), SeqSim(full)
    simK.reset({"din": 0, "clk": 0})
    simF.reset({"din": 0, "clk": 0})
    rng = random.Random(4321)
    outs = [f"q{i}" for i in range(4)]
    for k in range(30):
        v = rng.randint(0, 1)
        simK.clock_cycle({"din": v}, clock="clk")
        simF.clock_cycle({"din": v}, clock="clk")
        if k >= 4:   # after the depth-4 register flushes, both forms agree exactly
            assert [simK.value(o) for o in outs] == [simF.value(o) for o in outs], k


def test_combinational_cone_cuts_registers_and_is_acyclic():
    """combinational_cone() cuts every register: Q becomes a primary input, D and clock become
    primary outputs. The result is acyclic/combinational and has a static truth table, so two
    sequential designs can be compared on their cone with equivalent()."""
    from netlist import equivalent
    nl = build_toggle()                      # register output net is literally "q" here
    cone = nl.combinational_cone()
    assert not cone.is_sequential()
    cone.truth_table()                       # must not raise (it is combinational now)
    # the register output q is now a free primary input; its D (nq) and clk are primary outputs.
    assert "q" in cone.ports.inputs
    assert "nq" in cone.ports.outputs and "clk" in cone.ports.outputs
    # equivalent() works on the cone (compares the cone to itself).
    assert equivalent(cone, nl.combinational_cone())
    # the cone really computes the toggle next-state nq = NOT q (q in -> nq out flips).
    assert cone.outputs_for({"q": 0, "clk": 0})["nq"] == 1
    assert cone.outputs_for({"q": 1, "clk": 0})["nq"] == 0


def test_combinational_cone_distinguishes_different_next_state_logic():
    """The cone equivalence is a real check: a toggle (q_next = NOT q) and a hold (q_next = q)
    have DIFFERENT cones, so equivalent() on the cone tells them apart."""
    from netlist import equivalent
    toggle = Netlist("t",
                     [Cell("inv", "NOT", ["q"], "nq"),
                      Cell("ff", "DFF", ["nq"], "q", clock="clk")],
                     Ports(["clk"], ["q"]))
    hold = Netlist("h",
                   [Cell("ff", "DFF", ["q"], "q", clock="clk")],
                   Ports(["clk"], ["q"]))
    assert not equivalent(toggle.combinational_cone(), hold.combinational_cone())


def test_lowered_dff_matches_behavioural_over_a_schedule():
    """The cross-coupled-NOR master-slave reproduces the DFF after the first edge.

    The lowered latch has no async reset, so it powers on in an arbitrary settled state; the
    two forms are compared from the first clocked value onward, which is the physically
    meaningful comparison (a real NOR latch is undefined until first clocked)."""
    nl = build_dff()
    low = nl.to_nor()
    simB = SeqSim(nl)
    simL = SeqSim(low)
    simB.reset({"d": 0, "clk": 0})
    simL.reset({"d": 0, "clk": 0})
    rng = random.Random(12345)
    # one cycle to flush the single register, then they must agree exactly.
    first = True
    for _ in range(40):
        v = rng.randint(0, 1)
        simB.clock_cycle({"d": v}, clock="clk")
        simL.clock_cycle({"d": v}, clock="clk")
        if first:
            first = False  # after one edge a depth-1 register is flushed
        assert simL.value("q") == v
        assert simB.value("q") == simL.value("q")


# --- 3: the one-edge latency matches gate_model.py --------------------------------

def test_registered_nor_matches_gate_model_nortile():
    """y = DFF(NOR(a,b), clk) reproduces gate_model.single_nor(2) cycle for cycle, which is
    the one-edge register latency the gate model specifies."""
    nl = build_registered_nor()
    sim = SeqSim(nl)
    sim.reset({"a": 0, "b": 0, "clk": 0})

    gm = single_nor(2)
    gm.reset({"a": 0, "b": 0})

    rng = random.Random(7)
    for _ in range(32):
        a, bv = rng.randint(0, 1), rng.randint(0, 1)
        # our register: present a,b for the cycle, capture NOR(a,b) on the edge.
        sim.clock_cycle({"a": a, "b": bv}, clock="clk")
        # gate_model: drive then step latches NOR of the held inputs.
        gm.drive({"a": a, "b": bv})
        gm.step()
        assert sim.value("y") == gm.value("y") == gm_nor((a, bv)), f"a={a} b={bv}"


def test_registered_nor_lowered_also_matches_gate_model():
    """The same equivalence holds for the all-NOR lowered registered NOR (after flush)."""
    low = build_registered_nor().to_nor()
    sim = SeqSim(low)
    sim.reset({"a": 0, "b": 0, "clk": 0})
    gm = single_nor(2)
    gm.reset({"a": 0, "b": 0})
    rng = random.Random(99)
    # flush one edge (depth-1 register), then compare.
    for k in range(32):
        a, bv = rng.randint(0, 1), rng.randint(0, 1)
        sim.clock_cycle({"a": a, "b": bv}, clock="clk")
        gm.drive({"a": a, "b": bv})
        gm.step()
        if k >= 1:
            assert sim.value("y") == gm.value("y"), f"a={a} b={bv} cyc={k}"


def test_one_edge_latency_explicit():
    """Driving a new input mid-cycle only affects the registered output after the next edge,
    mirroring gate_model.test_one_edge_latency."""
    nl = build_registered_nor()
    sim = SeqSim(nl)
    sim.reset({"a": 0, "b": 0, "clk": 0})
    sim.clock_cycle({"a": 0, "b": 0}, clock="clk")
    assert sim.value("y") == 1                       # NOR(0,0) = 1

    # change a with no new edge: the registered output holds the old value.
    sim.set_inputs({"a": 1})
    sim.settle()
    assert sim.value("y") == 1                       # still last edge's value
    sim.clock_cycle({"a": 1, "b": 0}, clock="clk")
    assert sim.value("y") == 0                       # NOR(1,0) = 0, now latched


# --- 4: the combinational path is unchanged ---------------------------------------

def test_combinational_simulate_unchanged():
    b = NetlistBuilder("comb")
    a = b.declare_input("a")
    bb = b.declare_input("b")
    b.alias_output("y", b.nor([a, bb]))
    nl = b.finish()
    tt = {tuple(sorted(iv.items())): ov for iv, ov in nl.truth_table()}
    assert tt[(("a", 0), ("b", 0))] == {"y": 1}
    assert tt[(("a", 0), ("b", 1))] == {"y": 0}
    assert tt[(("a", 1), ("b", 0))] == {"y": 0}
    assert tt[(("a", 1), ("b", 1))] == {"y": 0}


def test_simulate_rejects_sequential_netlist():
    nl = build_dff()
    with pytest.raises(ValueError, match="sequential"):
        nl.simulate({"d": 1, "clk": 1})
    with pytest.raises(ValueError):
        nl.truth_table()


def test_validate_rejects_clock_on_combinational_cell():
    bad = Netlist(
        "bad",
        [Cell("g0", "NOR", ["a"], "y", clock="clk")],
        Ports(["a", "clk"], ["y"]),
    )
    with pytest.raises(ValueError, match="must not carry a clock"):
        bad.validate()


def test_validate_rejects_dff_without_clock():
    bad = Netlist(
        "bad",
        [Cell("ff", "DFF", ["d"], "q", clock=None)],
        Ports(["d"], ["q"]),
    )
    with pytest.raises(ValueError, match="no clock net"):
        bad.validate()


def test_validate_rejects_undriven_clock():
    bad = Netlist(
        "bad",
        [Cell("ff", "DFF", ["d"], "q", clock="missing")],
        Ports(["d"], ["q"]),
    )
    with pytest.raises(ValueError, match="clock"):
        bad.validate()


# --- 5: structural sanity ---------------------------------------------------------

def test_toggle_flip_flop_divides_clock_by_two():
    """A feedback T flip-flop alternates every cycle, in both the behavioural and the lowered
    all-NOR form (the lowering closes the feedback loop with cross-coupled NOR latches)."""
    for nl in (build_toggle(), build_toggle().to_nor()):
        sim = SeqSim(nl)
        sim.reset({"clk": 0})
        outs = [(_, sim.clock_cycle({}, clock="clk"), sim.value("q"))[2] for _ in range(8)]
        # strictly alternating: every adjacent pair differs.
        assert all(outs[i] != outs[i + 1] for i in range(len(outs) - 1)), outs


def test_shift_register_walks_one_stage_per_cycle():
    nl = build_shift(4)
    sim = SeqSim(nl)
    sim.reset({"din": 0, "clk": 0})
    # push a single 1 then zeros; it should walk q0 -> q1 -> q2 -> q3.
    expected = [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
        [0, 0, 0, 0],
    ]
    din = [1, 0, 0, 0, 0]
    for v, exp in zip(din, expected):
        sim.clock_cycle({"din": v}, clock="clk")
        assert [sim.value(f"q{i}") for i in range(4)] == exp, f"din={v}"


def test_shift_register_lowered_matches_after_flush():
    nl = build_shift(4)
    low = nl.to_nor()
    for c in low.cells:
        assert c.type in BUILDABLE
    simB = SeqSim(nl)
    simL = SeqSim(low)
    simB.reset({"din": 0, "clk": 0})
    simL.reset({"din": 0, "clk": 0})
    rng = random.Random(2024)
    outs = [f"q{i}" for i in range(4)]
    for k in range(30):
        v = rng.randint(0, 1)
        simB.clock_cycle({"din": v}, clock="clk")
        simL.clock_cycle({"din": v}, clock="clk")
        if k >= 4:   # after depth-4 register is flushed, the forms agree exactly
            assert [simB.value(o) for o in outs] == [simL.value(o) for o in outs], k


def test_sequential_json_round_trip():
    nl = build_dff()
    doc = json.loads(nl.to_json())
    nl2 = Netlist.from_dict(doc)
    ff = [c for c in nl2.cells if c.type == "DFF"][0]
    assert ff.clock == "clk"
    assert ff.reset == 0
    assert len(ff.inputs) == 1
    # and it still steps identically after a round trip.
    sim = SeqSim(nl2)
    sim.reset({"d": 0, "clk": 0})
    sim.clock_cycle({"d": 1}, clock="clk")
    assert sim.value("q") == 1


def test_old_json_without_sequential_fields_still_loads():
    """Backward compatibility: scenario JSON written before the DFF existed has no clock/reset
    keys and must still load (the fields default)."""
    old = {
        "name": "old",
        "cells": [{"id": "g0", "type": "NOR", "inputs": ["a"], "output": "y"}],
        "ports": {"inputs": ["a"], "outputs": ["y"]},
    }
    nl = Netlist.from_dict(old)
    assert nl.cells[0].clock is None
    assert nl.cells[0].reset == 0
    assert not nl.is_sequential()


def test_seqsim_raises_on_oscillator():
    """A bare cross-coupled inverter ring with no register cannot settle and must raise,
    proving settle() does not silently accept a non-converging design (mirrors
    gate_model.test_settle_raises_on_oscillator)."""
    # y = NOR(y): a single-input NOR fed by its own output is an inverter ring.
    osc = Netlist("osc", [Cell("g0", "NOR", ["y"], "y")], Ports([], ["y"]))
    sim = SeqSim(osc)
    # reset() settles, which must raise on this oscillator.
    with pytest.raises(RuntimeError):
        sim.reset({})


# --- 6: the sequential equivalence contract (simulate_trace / sequential_equivalent) ----

def test_simulate_trace_drives_a_shift_register():
    """simulate_trace steps a clocked netlist one full cycle per trace entry and records the
    primary outputs (and any requested state nets) per cycle."""
    nl = build_shift(3)
    trace = [{"din": v} for v in (1, 0, 0, 1, 1, 0)]
    rows = simulate_trace(nl, trace, clock="clk", state_nets=["q0", "q1", "q2"])
    assert len(rows) == len(trace)
    # the single 1 then 0,0 walks q0 -> q1 -> q2.
    assert rows[0]["q0"] == 1 and rows[0]["q1"] == 0 and rows[0]["q2"] == 0
    assert rows[1]["q1"] == 1
    assert rows[2]["q2"] == 1


def test_sequential_equivalent_dff_vs_itself():
    """A sequential netlist is trivially sequential_equivalent to itself over any trace,
    outputs and state alike, from cycle 0 (same level, same reset)."""
    nl = build_dff()
    trace = [{"d": v} for v in (1, 0, 1, 1, 0, 1, 0, 0)]
    assert sequential_equivalent(nl, nl, trace, clock="clk")
    assert sequential_equivalent(nl, nl, trace, clock="clk", state_nets=["q"])


def test_sequential_equivalent_dff_vs_lowered_after_flush():
    """A behavioural DFF and its all-NOR lowering produce the same OUTPUT trace once the
    single register is flushed (skip_cycles=1), the sequential analogue of the combinational
    equivalent() check for a registered design with an external data path."""
    nl = build_dff()
    low = nl.to_nor()
    rng = random.Random(2025)
    trace = [{"d": rng.randint(0, 1)} for _ in range(40)]
    # depth-1 register: equal from the second cycle on (the first flushes the power-on state).
    assert sequential_equivalent(nl, low, trace, clock="clk", skip_cycles=1)


def test_sequential_equivalent_shift_chain_vs_lowered_after_flush():
    nl = build_shift(4)
    low = nl.to_nor()
    rng = random.Random(11)
    trace = [{"din": rng.randint(0, 1)} for _ in range(50)]
    # depth-4 chain: equal after the 4-deep pipeline is flushed.
    assert sequential_equivalent(nl, low, trace, clock="clk", skip_cycles=4)


def test_sequential_equivalent_distinguishes_different_registers():
    """Two registers with different data inputs (q = DFF(d) vs q = DFF(NOT d)) are NOT
    sequential_equivalent, so the checker is not vacuously true."""
    a = build_dff()                         # q = DFF(d)
    b = NetlistBuilder("ndff")
    d = b.declare_input("d")
    clk = b.declare_input("clk")
    nd = b.inv(d)
    q = b.dff(nd, clk)                       # q = DFF(NOT d)
    b.alias_output("q", q)
    inv_dff = b.finish()
    trace = [{"d": v} for v in (0, 1, 0, 1, 1, 0)]
    assert not sequential_equivalent(a, inv_dff, trace, clock="clk")


def test_dff_into_drives_a_reserved_feedback_net():
    """NetlistBuilder.dff_into drives a register output net reserved up front, so a feedback
    loop (the register's data depends on its own output) can be wired. A toggle built this way
    alternates, and lowers to buildable NOR."""
    b = NetlistBuilder("tog")
    clk = b.declare_input("clk")
    q = b.fresh_net()
    nq = b.inv(q)                            # NOT q (references the reserved net)
    b.dff_into(nq, clk, q)                   # q = DFF(NOT q) driving the reserved net
    b.alias_output("q", q)
    nl = b.finish()
    nl.validate()
    sim = SeqSim(nl)
    sim.reset({"clk": 0})
    outs = []
    for _ in range(8):
        sim.clock_cycle({}, clock="clk")
        outs.append(sim.value("q"))
    assert all(outs[i] != outs[i + 1] for i in range(len(outs) - 1)), outs
    for c in nl.to_nor().cells:
        assert c.type in BUILDABLE
