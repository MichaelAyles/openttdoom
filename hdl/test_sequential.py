"""Tests for the SEQUENTIAL path: m.d.sync Amaranth -> register + NOR netlist, and the
sequential equivalence checker. The sequential counterpart of hdl/test_adder.py.

This is the worked example end to end IN SOFTWARE the brief asks for: a toggle flip-flop and
an n-bit counter, each written behaviourally (Amaranth m.d.sync), lowered to a register + NOR
netlist, simulated correct over several clock cycles, and shown equivalent to a plain Python
behavioural reference. It exercises the new contract additions in synth/netlist.py:
NetlistBuilder.dff_into (a register driving a reserved feedback net), simulate_trace (step a
clocked netlist over an input trace), and sequential_equivalent (compare two clocked netlists
by their output AND state traces, the sequential analogue of equivalent()).

The checks, in order of trust:
  1. The plain Python references (toggle_reference, counter_reference) define the ground truth.
  2. The behavioural Amaranth Toggle / Counter (m.d.sync) match the references in the amaranth
     simulator over several cycles, with the same reset and enable behaviour.
  3. The structural gate + DFF netlists (build_toggle_ff, build_counter) match the references
     exactly when stepped with SeqSim / simulate_trace.
  4. The structural netlists lower to the buildable {NOR, CONST0, CONST1} set (plus the latch
     feedback) and keep the same transition function. Because the all-NOR latch has no async
     reset (see NetlistBuilder.dff_nor), a SELF-FEEDBACK register such as this counter powers
     on at a physically arbitrary state, so the lowered form runs the SAME increments but from
     a constant state offset; we prove that offset is constant (a rigorous equivalence of the
     transition function, honest about the power-on state).
  5. sequential_equivalent / simulate_trace contract behaviour, including that it rejects
     mismatched ports and catches a genuinely different sequential design.
  6. OPTIONAL real-yosys cross-check (synth/yosys_seq.py): yosys emits $_DFF_P_ flops that
     techmap to the register cell; that flop has a real sync reset, so the yosys netlist
     matches the reference exactly (no offset). Skipped cleanly when no yosys is present.

Run only this file:
    python -m pytest hdl/test_sequential.py -q
"""

from __future__ import annotations

import random

import pytest

from amaranth.hdl import Module
from amaranth.sim import Simulator

from netlist import (
    BUILDABLE,
    Cell,
    Netlist,
    Ports,
    SeqSim,
    sequential_equivalent,
    simulate_trace,
)
from sequential import (
    Counter,
    Toggle,
    build_counter,
    build_toggle_ff,
    counter_reference,
    toggle_reference,
)


# --- helpers ----------------------------------------------------------------------

def _counter_value(row: dict, width: int) -> int:
    return sum((row[f"q{i}"] << i) for i in range(width))


def _en_trace(n: int, seed: int) -> list:
    rng = random.Random(seed)
    return [rng.randint(0, 1) for _ in range(n)]


# --- 1: the Python references are self-consistent ground truth ---------------------

def test_toggle_reference_alternates():
    out = toggle_reference(10)
    assert out == [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    assert all(out[i] != out[i + 1] for i in range(len(out) - 1))


def test_counter_reference_counts_and_holds():
    # all enabled: 1,2,3,0,1,2,...
    assert counter_reference([1] * 6, 2) == [1, 2, 3, 0, 1, 2]
    # enable low holds the value.
    assert counter_reference([1, 1, 0, 0, 1], 2) == [1, 2, 2, 2, 3]
    # 3-bit wrap at 8.
    assert counter_reference([1] * 9, 3) == [1, 2, 3, 4, 5, 6, 7, 0, 1]


# --- 2: behavioural Amaranth (m.d.sync) matches the references --------------------

def test_behavioural_toggle_divides_clock():
    dut = Toggle()
    m = Module()
    m.submodules.dut = dut
    got = []

    async def tb(ctx):
        for _ in range(10):
            await ctx.tick()
            got.append(ctx.get(dut.q))

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()
    assert got == toggle_reference(10)


def test_behavioural_counter_matches_reference():
    width = 3
    dut = Counter(width)
    m = Module()
    m.submodules.dut = dut
    en_trace = _en_trace(24, seed=11)
    got = []

    async def tb(ctx):
        for en in en_trace:
            ctx.set(dut.en, en)
            await ctx.tick()
            got.append(ctx.get(dut.q))

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()
    assert got == counter_reference(en_trace, width)


# --- 3: structural gate + DFF netlist matches the references ----------------------

def test_structural_toggle_matches_reference():
    nl = build_toggle_ff()
    nl.validate()
    assert nl.is_sequential()
    assert nl.ports.inputs == ["clk"]
    assert nl.ports.outputs == ["q"]
    sim = SeqSim(nl)
    sim.reset({"clk": 0})
    got = []
    for _ in range(10):
        sim.clock_cycle({}, clock="clk")
        got.append(sim.value("q"))
    assert got == toggle_reference(10)


def test_structural_counter_matches_reference():
    for width in (2, 3, 4):
        nl = build_counter(width)
        nl.validate()
        assert nl.ports.inputs == ["clk", "en"]
        assert nl.ports.outputs == [f"q{i}" for i in range(width)]
        en_trace = _en_trace(40, seed=width)
        rows = simulate_trace(nl, [{"en": e} for e in en_trace], clock="clk")
        got = [_counter_value(r, width) for r in rows]
        assert got == counter_reference(en_trace, width), f"width={width}"


def test_structural_counter_holds_when_disabled():
    nl = build_counter(3)
    sim = SeqSim(nl)
    sim.reset({"clk": 0, "en": 0})
    sim.clock_cycle({"en": 1}, clock="clk")
    sim.clock_cycle({"en": 1}, clock="clk")
    assert [sim.value(f"q{i}") for i in range(3)] == [0, 1, 0]   # value 2
    for _ in range(5):                                           # disabled: must hold 2
        sim.clock_cycle({"en": 0}, clock="clk")
        assert [sim.value(f"q{i}") for i in range(3)] == [0, 1, 0]
    sim.clock_cycle({"en": 1}, clock="clk")                      # one more increment -> 3
    assert [sim.value(f"q{i}") for i in range(3)] == [1, 1, 0]


# --- 4: lowering to buildable NOR, and the transition function is preserved -------

def test_structural_toggle_lowers_to_buildable():
    low = build_toggle_ff().to_nor()
    assert not low.is_sequential()          # the DFF became cross-coupled NOR latches
    for c in low.cells:
        assert c.type in BUILDABLE, f"non-buildable {c.type}"
    # the lowered toggle still alternates strictly (its own sequence), even though its
    # power-on phase is arbitrary (no async reset on the raw NOR latch).
    sim = SeqSim(low)
    sim.reset({"clk": 0})
    outs = []
    for _ in range(10):
        sim.clock_cycle({}, clock="clk")
        outs.append(sim.value("q"))
    assert all(outs[i] != outs[i + 1] for i in range(len(outs) - 1)), outs


def test_structural_counter_lowers_to_buildable():
    low = build_counter(3).to_nor()
    for c in low.cells:
        assert c.type in BUILDABLE, f"non-buildable {c.type}"
    assert set(low.ports.inputs) == {"clk", "en"}
    assert low.ports.outputs == ["q0", "q1", "q2"]


def test_lowered_counter_runs_same_increments_with_constant_offset():
    """The behavioural-DFF counter and its all-NOR lowering compute the SAME transition
    function (same increments under the same enable trace). The all-NOR master-slave latch
    has no async reset, so this SELF-FEEDBACK counter powers on at a physically arbitrary
    state and the two forms differ by a CONSTANT state offset, never a varying one. Proving
    the offset is constant across a long random trace is the honest equivalence statement for
    a register with no external data path to flush its initial state (see dff_nor's docstring).
    """
    width = 3
    hi = build_counter(width)
    low = hi.to_nor()
    en_trace = _en_trace(60, seed=7)
    trace = [{"en": e} for e in en_trace]
    hi_rows = simulate_trace(hi, trace, clock="clk")
    low_rows = simulate_trace(low, trace, clock="clk")
    mask = (1 << width) - 1
    offsets = {
        (_counter_value(h, width) - _counter_value(l, width)) & mask
        for h, l in zip(hi_rows, low_rows)
    }
    assert len(offsets) == 1, f"offset must be constant, got {offsets}"


# --- 5: the sequential equivalence checker itself ---------------------------------

def test_sequential_equivalent_same_netlist_built_twice():
    """Two independent structural builds of the same counter are exactly equivalent from
    cycle 0 (same level, deterministic reset, no power-on ambiguity)."""
    a = build_counter(3)
    b = build_counter(3)
    trace = [{"en": e} for e in _en_trace(50, seed=3)]
    assert sequential_equivalent(a, b, trace, clock="clk")
    # and including the internal register state, not just outputs.
    assert sequential_equivalent(a, b, trace, clock="clk", state_nets=["q0", "q1", "q2"])


def test_sequential_equivalent_rejects_mismatched_ports():
    a = build_counter(2)
    b = build_counter(3)        # different output ports (q2 extra)
    trace = [{"en": 1} for _ in range(4)]
    assert not sequential_equivalent(a, b, trace, clock="clk")


def test_sequential_equivalent_catches_a_different_design():
    """A 2-bit UP counter and a 2-bit DOWN counter share ports but compute different
    sequences, so sequential_equivalent must return False over a driving trace."""
    up = build_counter(2)

    # a 2-bit DOWN counter: q := (q - 1) mod 4 while enabled. Decrement == add the constant 3
    # (two's complement of 1 in 2 bits is 0b11), so each addend bit is 1, gated by en. Built
    # structurally with the same dff_into feedback pattern as build_counter, a real ripple add.
    from netlist import NetlistBuilder
    b = NetlistBuilder("down2")
    clk = b.declare_input("clk")
    en = b.declare_input("en")
    q = [b.fresh_net() for _ in range(2)]
    carry = en                       # carry-in = bit 0 of the constant 3, gated by en
    for i in range(2):
        addend = en                  # constant 3 == 0b11, every bit set, gated by en
        axb = b.xor2(q[i], addend)
        qn = b.xor2(axb, carry)              # sum = q ^ addend ^ carry
        cc1 = b.and_([q[i], addend])
        cc2 = b.and_([axb, carry])
        carry = b.or_([cc1, cc2])            # carry out (majority)
        b.dff_into(qn, clk, q[i])
        b.alias_output(f"q{i}", q[i])
    down = b.finish()

    trace = [{"en": 1} for _ in range(6)]
    # up: 1,2,3,0,1,2 ; down: 3,2,1,0,3,2 -> different sequences.
    assert not sequential_equivalent(up, down, trace, clock="clk")


def test_simulate_trace_records_outputs_and_state():
    nl = build_counter(2)
    trace = [{"en": 1}, {"en": 0}, {"en": 1}]
    rows = simulate_trace(nl, trace, clock="clk", state_nets=["q0", "q1"])
    assert len(rows) == 3
    # outputs present, and state nets too.
    assert set(rows[0]) >= {"q0", "q1"}
    assert [_counter_value(r, 2) for r in rows] == [1, 1, 2]


# --- 6: the full worked example, end to end ---------------------------------------

def test_counter_worked_example_end_to_end():
    """Behavioural Amaranth -> structural register+NOR netlist -> simulate -> equivalent,
    all in software, for a 2-bit up counter, the brief's worked example.

    Stage A: behavioural Amaranth Counter (m.d.sync) over a clock trace == reference.
    Stage B: structural gate + DFF netlist over the SAME trace == reference (so the netlist
             realises the behavioural circuit).
    Stage C: the structural netlist lowers to buildable NOR and computes the same increment
             transition (constant power-on offset only).
    """
    width = 2
    en_trace = _en_trace(20, seed=42)
    ref = counter_reference(en_trace, width)

    # Stage A: behavioural amaranth.
    dut = Counter(width)
    m = Module()
    m.submodules.dut = dut
    beh = []

    async def tb(ctx):
        for en in en_trace:
            ctx.set(dut.en, en)
            await ctx.tick()
            beh.append(ctx.get(dut.q))

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()
    assert beh == ref, "behavioural amaranth counter != reference"

    # Stage B: structural netlist.
    nl = build_counter(width)
    rows = simulate_trace(nl, [{"en": e} for e in en_trace], clock="clk")
    struct = [_counter_value(r, width) for r in rows]
    assert struct == ref, "structural netlist != reference"

    # Stage C: buildable lowering preserves the transition function (constant offset).
    low = nl.to_nor()
    for c in low.cells:
        assert c.type in BUILDABLE
    low_rows = simulate_trace(low, [{"en": e} for e in en_trace], clock="clk")
    mask = (1 << width) - 1
    offsets = {
        (s - _counter_value(l, width)) & mask for s, l in zip(struct, low_rows)
    }
    assert len(offsets) == 1, f"lowering changed the transition function, offsets={offsets}"


# --- 7: optional real-yosys sequential cross-check --------------------------------

def test_yosys_sequential_crosscheck_if_available():
    """If a real yosys is reachable, synthesise the behavioural Counter through it to a
    $_DFF_P_ + NOR netlist and verify it. yosys's flop has a genuine synchronous reset to 0,
    so unlike the raw-NOR self-feedback latch it powers on at 0 and matches the reference
    EXACTLY (no offset). The netlist must be sequential, lower to buildable NOR, and add up.
    Skipped cleanly when no yosys binary is present.
    """
    from sequential import synth_counter_via_yosys

    try:
        yl = synth_counter_via_yosys(2)
    except RuntimeError as exc:
        pytest.skip(f"no yosys available: {exc}")

    assert yl.is_sequential()
    assert yl.clocks() == ["clk"]
    assert set(yl.ports.outputs) == {"q0", "q1"}
    # amaranth's sync domain adds a synchronous reset port; it is a primary input here.
    assert "en" in yl.ports.inputs and "clk" in yl.ports.inputs

    en_trace = _en_trace(24, seed=5)
    ref = counter_reference(en_trace, 2)
    # drive rst = 0 throughout (the structural counter has no reset port).
    rst_in = "rst" if "rst" in yl.ports.inputs else None
    yl_trace = [{"en": e, **({rst_in: 0} if rst_in else {})} for e in en_trace]
    rows = simulate_trace(yl, yl_trace, clock="clk")
    got = [_counter_value(r, 2) for r in rows]
    assert got == ref, f"yosys counter {got} != reference {ref}"

    low = yl.to_nor()
    for c in low.cells:
        assert c.type in BUILDABLE, f"yosys lowered cell {c.id} is {c.type}"
    print("yosys sequential stats:", yl.stats(), "lowered:", low.stats())
