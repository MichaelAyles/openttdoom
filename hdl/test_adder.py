"""Tests for the 4-bit adder: behavioural reference, structural netlist, NOR lowering.

Run only this file (other modules are built concurrently):
    python -m pytest hdl/test_adder.py -q

The checks, in order of trust:
  1. The behavioural Adder4 is simulated with amaranth over all 512 input combos.
  2. The structural Netlist is evaluated over all 512 combos and must equal a + b + cin.
  3. The structural Netlist lowered with to_nor() must be equivalent and fully buildable.
  4. An OPTIONAL real-yosys cross-check, skipped cleanly if no yosys is reachable.
"""

from __future__ import annotations

import pytest

from amaranth.hdl import Module
from amaranth.sim import Simulator

from netlist import BUILDABLE, Netlist, Ports, equivalent
from adder import Adder4, build_adder4_netlist, synth_adder4_via_yosys


# --- shared helpers ---------------------------------------------------------------

def _all_combos():
    for a in range(16):
        for b in range(16):
            for cin in (0, 1):
                yield a, b, cin


def _netlist_inputs(a: int, b: int, cin: int) -> dict:
    iv = {"cin": cin}
    for i in range(4):
        iv[f"a{i}"] = (a >> i) & 1
        iv[f"b{i}"] = (b >> i) & 1
    return iv


def _netlist_sum(ov: dict) -> int:
    return sum((ov[f"s{i}"] << i) for i in range(4)) + (ov["cout"] << 4)


# --- 1: behavioural reference over all 512 combos ---------------------------------

def test_behavioural_adder4_all_combos():
    dut = Adder4()
    m = Module()
    m.submodules.dut = dut

    results = {}

    async def testbench(ctx):
        for a, b, cin in _all_combos():
            ctx.set(dut.a, a)
            ctx.set(dut.b, b)
            ctx.set(dut.cin, cin)
            await ctx.delay(1e-6)
            s = ctx.get(dut.s)
            cout = ctx.get(dut.cout)
            results[(a, b, cin)] = s + 16 * cout

    sim = Simulator(m)
    sim.add_testbench(testbench)
    sim.run()

    assert len(results) == 512
    for (a, b, cin), got in results.items():
        assert got == a + b + cin, f"behavioural {a}+{b}+{cin} gave {got}"


# --- 2 and 3: structural netlist and NOR lowering ---------------------------------

def test_structural_netlist_adds():
    nl = build_adder4_netlist()
    assert nl.ports.inputs == ["a0", "a1", "a2", "a3", "b0", "b1", "b2", "b3", "cin"]
    assert nl.ports.outputs == ["s0", "s1", "s2", "s3", "cout"]

    for a, b, cin in _all_combos():
        ov = nl.outputs_for(_netlist_inputs(a, b, cin))
        assert _netlist_sum(ov) == a + b + cin, f"structural {a}+{b}+{cin}"


def test_structural_lowers_to_buildable_nor():
    nl = build_adder4_netlist()
    lowered = nl.to_nor()

    # the lowered netlist must be logically identical to the structural one.
    assert equivalent(nl, lowered)

    # and every surviving cell must be in the buildable set {NOR, CONST0, CONST1}.
    for c in lowered.cells:
        assert c.type in BUILDABLE, f"lowered cell {c.id} is non-buildable {c.type}"

    stats = lowered.stats()
    # report the gate count so the run log shows it.
    print("structural lowered NOR stats:", stats)
    assert stats.get("NOR", 0) > 0


# --- 4: optional real-yosys cross-check -------------------------------------------

def test_yosys_crosscheck_if_available():
    """If a real yosys is reachable, synthesise via it and verify the gate-level result.

    yosys does the flatten/opt/gate-lowering; the NOR techmap stays in Python. We check
    the imported netlist adds correctly over all 512 combos, is logically equivalent to the
    structural build (so the name "cross-check" is accurate: both compute the same function),
    and lowers to buildable NOR. Skipped cleanly when no yosys binary is present.
    """
    try:
        yl = synth_adder4_via_yosys()
    except RuntimeError as exc:
        pytest.skip(f"no yosys available: {exc}")

    assert set(yl.ports.outputs) == {"s0", "s1", "s2", "s3", "cout"}
    assert set(yl.ports.inputs) == {
        "a0", "a1", "a2", "a3", "b0", "b1", "b2", "b3", "cin"
    }

    # the real cross-check: the yosys netlist must be equivalent to the structural build,
    # not merely correct against the arithmetic spec. yosys lists its input ports in its
    # own bit allocation order, so we present yl under the structural canonical port order
    # before comparing. equivalent() then checks identical I/O plus the same truth table.
    ref = build_adder4_netlist()
    yl_canon = Netlist(yl.name, yl.cells, Ports(list(ref.ports.inputs), list(ref.ports.outputs)))
    yl_canon.validate()
    assert equivalent(yl_canon, ref)

    for a, b, cin in _all_combos():
        ov = yl.outputs_for(_netlist_inputs(a, b, cin))
        assert _netlist_sum(ov) == a + b + cin, f"yosys {a}+{b}+{cin}"

    lowered = yl.to_nor()
    for c in lowered.cells:
        assert c.type in BUILDABLE, f"yosys lowered cell {c.id} is {c.type}"
    print("yosys gate-level stats:", yl.stats())
    print("yosys lowered NOR stats:", lowered.stats())
