"""Tests for the CHIP-8 8XY_ ALU: behavioural reference, structural netlist, NOR lowering,
then the full place-and-route pipeline.

Run only this file (other modules are built concurrently):
    python -m pytest hdl/test_alu.py -q

The checks, in order of trust:
  1. The plain Python alu8_reference is pinned against golden/chip8.py::_arith semantics
     on a strong sample, so the reference itself is anchored to the project's oracle.
  2. The behavioural Alu8 is simulated with amaranth: all 256x256 pairs for ADD and SUB,
     and a good sample for the other ops, all against alu8_reference.
  3. The structural build_alu8_netlist() is evaluated over the same inputs and must equal
     alu8_reference for every op.
  4. The structural netlist lowered with to_nor() must be equivalent and fully buildable.
  5. The lowered NOR netlist places AND routes: drc() == 0 and verify_equivalence with
     require_routed=True, proving the ALU closes through the backend like the adder did.
"""

from __future__ import annotations

import pytest

from amaranth.hdl import Module
from amaranth.sim import Simulator

from netlist import BUILDABLE
from alu import (
    Alu8, alu8_reference, build_alu8_netlist,
    DEFINED_OPS, OP_ADD, OP_SUB, OP_NAME,
)


# --- shared helpers ---------------------------------------------------------------

def _netlist_inputs(vx: int, vy: int, op: int) -> dict:
    iv = {}
    for i in range(8):
        iv[f"vx{i}"] = (vx >> i) & 1
        iv[f"vy{i}"] = (vy >> i) & 1
    for i in range(4):
        iv[f"op{i}"] = (op >> i) & 1
    return iv


def _netlist_result(ov: dict) -> tuple:
    r = sum((ov[f"r{i}"] << i) for i in range(8))
    return r, ov["vf"]


def _sample_pairs(step: int):
    """A deterministic sample of (vx, vy) pairs covering edges and a coarse grid."""
    edges = [0, 1, 2, 0x0F, 0x10, 0x55, 0x7F, 0x80, 0x81, 0xAA, 0xFE, 0xFF]
    pairs = set()
    for vx in edges:
        for vy in edges:
            pairs.add((vx, vy))
    for vx in range(0, 256, step):
        for vy in range(0, 256, step):
            pairs.add((vx, vy))
    return sorted(pairs)


def _netlists_equivalent_sampled(a, b, step: int = 7) -> bool:
    """Equivalence of two ALU-shaped netlists by simulating both over a strong sample.

    The contract's equivalent() enumerates the full 2^N truth table. With 20 input nets
    that is 2^20 = ~1M rows per netlist, far too slow for a test. Both netlists here are
    the SAME circuit shape (same 20 named ports), so we instead drive identical inputs
    through both and compare outputs over every defined op and a wide (vx, vy) sample.
    This is the honest preservation check: it directly compares the two functions on the
    inputs that matter (all ops, edges, a grid), without claiming a full proof.
    """
    if set(a.ports.inputs) != set(b.ports.inputs):
        return False
    if set(a.ports.outputs) != set(b.ports.outputs):
        return False
    sample = _sample_pairs(step)
    for op in DEFINED_OPS:
        for vx, vy in sample:
            iv = _netlist_inputs(vx, vy, op)
            if a.outputs_for(iv) != b.outputs_for(iv):
                return False
    return True


# --- 1: the Python reference is anchored to golden/chip8.py ------------------------

def test_reference_matches_golden_chip8():
    """alu8_reference must match golden/chip8.py::_arith for every defined op.

    We drive the real Chip8 _arith with VX in V[1], VY in V[2], result back to V[1],
    flag in V[0xF], and compare. This pins our reference to the project oracle rather than
    to our own restatement of the semantics. LD's VF is excluded (the oracle leaves VF
    unchanged; our combinational ALU defines it as 0, see alu.py docstring).
    """
    from chip8 import Chip8

    sample = _sample_pairs(17)
    for op in DEFINED_OPS:
        for vx, vy in sample:
            c = Chip8()                       # classic quirk defaults: vf_reset, shift_use_vy
            c.V[1] = vx
            c.V[2] = vy
            c.V[0xF] = 0                       # known prior VF so LD comparison is defined
            c._arith(1, 2, op)
            golden_res = c.V[1]
            golden_vf = c.V[0xF]

            ref_res, ref_vf = alu8_reference(vx, vy, op)
            assert ref_res == golden_res, (
                f"{OP_NAME[op]} result vx={vx} vy={vy}: ref {ref_res} != golden {golden_res}")
            if op != 0x0:                      # LD: VF is don't-care vs the oracle
                assert ref_vf == golden_vf, (
                    f"{OP_NAME[op]} vf vx={vx} vy={vy}: ref {ref_vf} != golden {golden_vf}")


# --- 2: behavioural Alu8 vs the reference -----------------------------------------

def test_behavioural_alu8_add_sub_exhaustive():
    """ADD and SUB over all 256x256 input pairs, against alu8_reference."""
    dut = Alu8()
    m = Module()
    m.submodules.dut = dut

    mismatches = []

    async def testbench(ctx):
        for op in (OP_ADD, OP_SUB):
            ctx.set(dut.op, op)
            for vx in range(256):
                ctx.set(dut.vx, vx)
                for vy in range(256):
                    ctx.set(dut.vy, vy)
                    await ctx.delay(1e-7)
                    r = ctx.get(dut.result)
                    vf = ctx.get(dut.vf)
                    exp_r, exp_vf = alu8_reference(vx, vy, op)
                    if (r, vf) != (exp_r, exp_vf):
                        mismatches.append((OP_NAME[op], vx, vy, (r, vf), (exp_r, exp_vf)))

    sim = Simulator(m)
    sim.add_testbench(testbench)
    sim.run()

    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[0]}"


def test_behavioural_alu8_all_ops_sample():
    """All nine defined ops over a good sample of input pairs, against alu8_reference."""
    dut = Alu8()
    m = Module()
    m.submodules.dut = dut

    sample = _sample_pairs(13)
    mismatches = []

    async def testbench(ctx):
        for op in DEFINED_OPS:
            ctx.set(dut.op, op)
            for vx, vy in sample:
                ctx.set(dut.vx, vx)
                ctx.set(dut.vy, vy)
                await ctx.delay(1e-7)
                r = ctx.get(dut.result)
                vf = ctx.get(dut.vf)
                exp_r, exp_vf = alu8_reference(vx, vy, op)
                if (r, vf) != (exp_r, exp_vf):
                    mismatches.append((OP_NAME[op], vx, vy, (r, vf), (exp_r, exp_vf)))

    sim = Simulator(m)
    sim.add_testbench(testbench)
    sim.run()

    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[0]}"


# --- 3: structural netlist vs the reference ---------------------------------------

def test_structural_netlist_all_ops():
    """build_alu8_netlist() must match alu8_reference for every defined op."""
    nl = build_alu8_netlist()
    assert nl.ports.inputs == (
        [f"vx{i}" for i in range(8)] + [f"vy{i}" for i in range(8)]
        + [f"op{i}" for i in range(4)])
    assert nl.ports.outputs == [f"r{i}" for i in range(8)] + ["vf"]

    sample = _sample_pairs(11)
    for op in DEFINED_OPS:
        for vx, vy in sample:
            ov = nl.outputs_for(_netlist_inputs(vx, vy, op))
            got = _netlist_result(ov)
            exp = alu8_reference(vx, vy, op)
            assert got == exp, f"structural {OP_NAME[op]} vx={vx} vy={vy}: {got} != {exp}"


def test_structural_add_sub_exhaustive_netlist():
    """ADD and SUB exhaustively (all 256x256) through the structural netlist."""
    nl = build_alu8_netlist()
    for op in (OP_ADD, OP_SUB):
        for vx in range(256):
            for vy in range(256):
                ov = nl.outputs_for(_netlist_inputs(vx, vy, op))
                got = _netlist_result(ov)
                exp = alu8_reference(vx, vy, op)
                assert got == exp, f"structural {OP_NAME[op]} vx={vx} vy={vy}: {got} != {exp}"


# --- 4: NOR lowering --------------------------------------------------------------

def test_structural_lowers_to_buildable_nor():
    nl = build_alu8_netlist()
    lowered = nl.to_nor()

    # the lowered netlist must be logically identical to the structural one, checked over
    # every op and a strong (vx, vy) sample (full 2^20 truth table is infeasible here).
    assert _netlists_equivalent_sampled(nl, lowered)

    # and every surviving cell must be in the buildable set {NOR, CONST0, CONST1}.
    for c in lowered.cells:
        assert c.type in BUILDABLE, f"lowered cell {c.id} is non-buildable {c.type}"

    s = nl.stats()
    ls = lowered.stats()
    print("structural ALU stats:", {k: v for k, v in s.items() if not k.startswith("_")})
    print("structural total cells:", s["_total_cells"], "nets:", s["_nets"])
    print("lowered NOR gate count:", ls.get("NOR", 0),
          "total cells:", ls["_total_cells"], "nets:", ls["_nets"])
    assert ls.get("NOR", 0) > 0


# --- 5: the full place-and-route pipeline -----------------------------------------

def test_alu8_places_and_routes():
    """The lowered ALU netlist places and routes with zero DRC violations, and the
    scenario reconstructed from the placement realises the same logic with every net routed.

    verify_equivalence() in check.py compares via the contract equivalent(), which would
    enumerate the full 2^20 truth table, so instead we reconstruct the netlist from the
    scenario with require_routed=True (which raises unless every net is physically and
    correctly routed) and then confirm the reconstruction computes the same function as the
    source over every op and a strong (vx, vy) sample.
    """
    from emit import build_scenario
    from check import drc, scenario_to_netlist

    lowered = build_alu8_netlist().to_nor()
    scen, rr = build_scenario(lowered)

    violations = drc(scen)
    assert violations == [], f"{len(violations)} DRC violations, first: {violations[0].detail}"

    routed, total = rr.coverage()
    print(f"ALU place-and-route: {len(scen.cells)} cells, {routed}/{total} nets routed, "
          f"{sum(len(r.bridges) for r in scen.routes)} bridge tiles, "
          f"map {scen.map_x}x{scen.map_y}")
    assert routed == total, f"only {routed}/{total} nets routed"

    # Reconstruct purely from the placed cells + routes; require_routed makes this raise
    # unless every net physically connects the pins its name claims. Then compare functions.
    rebuilt = scenario_to_netlist(scen, require_routed=True)
    assert _netlists_equivalent_sampled(lowered, rebuilt)
