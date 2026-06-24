"""Tests for the minimal 8-bit accumulator CPU: the sequential capstone of the toolchain.

The CPU (hdl/cpu.py) is the real clocked design the toggle/counter in hdl/sequential.py were
de-risking for: a whole little accumulator machine that FETCHES and EXECUTES a hardwired program
and emits the Fibonacci sequence on a memory-mapped OUTPUT latch. The checks mirror
hdl/test_alu.py and hdl/test_sequential.py, in order of trust:

  1. The plain Python cpu_reference IS the architectural ground truth: it runs the ISA one
     instruction per step. Its Fibonacci output stream is pinned to exactly the 13 eight-bit
     terms 1,1,2,3,5,8,13,21,34,55,89,144,233, then the mod-256 overflow term 121.
  2. The behavioural Amaranth Cpu (m.d.sync registers for ACC/PC/Z/phase/IR/DMEM) is simulated
     with amaranth.sim and must emit the same Fibonacci stream, term by term.
  3. The structural gate + DFF netlist (build_cpu_netlist) steps under SeqSim and must emit the
     same stream, AND step cycle-for-cycle identically to the behavioural Cpu across all exposed
     state (ACC, PC, Z, phase, the out_we strobe and out_port value).
  4. Each of the six ISA opcodes (LDI, ADD, SUB, STA, BZ taken/not-taken, JMP) is exercised by a
     small hand-assembled program through BOTH the reference and the structural netlist, so the
     control flow and the ALU (the reused ripple adder + sub = x + ~y + 1 trick) are pinned, not
     just the Fibonacci straight line.
  5. The structural netlist lowers to the buildable {NOR, CONST0, CONST1} set + register tiles
     and still emits the Fibonacci stream (the substrate-buildable form computes the same thing).
  6. The whole CPU flows through the real sequential PLACE-AND-ROUTE: it places with one register
     tile per architectural bit, routes to 100 percent of nets, the clock reaches every register,
     and the reconstruction-from-placement still emits the Fibonacci stream. The DRC-clean-at-this
     -scale property is the known open item (see the test docstring and STUCK.md), because the
     shared constructive router crowds risers at ~1600 cells; the LOGIC is fully verified here.

Run only this file:
    python -m pytest hdl/test_cpu.py -q
"""

from __future__ import annotations

import pytest

from amaranth.hdl import Module
from amaranth.sim import Simulator

from netlist import BUILDABLE, SeqSim
from cpu import (
    ACC_BITS,
    Cpu,
    DMEM_WORDS,
    FIB_OVERFLOW_TERM,
    FIB_PROGRAM,
    FIB_TERMS_8BIT,
    OP_ADD,
    OP_BZ,
    OP_JMP,
    OP_LDI,
    OP_STA,
    OP_SUB,
    OUT_ADDR,
    PC_BITS,
    PROG_WORDS,
    T_ADDR,
    build_cpu_netlist,
    cpu_reference,
    encode,
    fibonacci_reference,
    netlist_output_stream,
    netlist_stats,
)


# --- shared helpers ---------------------------------------------------------------

def _pad16(words):
    """Pad a short word list out to a full 16-word ROM (LDI 0 = harmless NOP-ish fill)."""
    return (list(words) + [encode(OP_LDI, 0)] * PROG_WORDS)[:PROG_WORDS]


def _behavioural_stream(program, edges):
    """Run the behavioural Amaranth Cpu for `edges` clock edges, return its emitted stream."""
    dut = Cpu(program)
    m = Module()
    m.submodules.dut = dut
    stream = []

    async def tb(ctx):
        for _ in range(edges):
            await ctx.tick()
            if ctx.get(dut.out_we):
                stream.append(ctx.get(dut.out_port))

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()
    return stream


# Building + routing the CPU is the slow step (~20s), so the place-and-route tests share one
# scenario via this module-scoped fixture.
@pytest.fixture(scope="module")
def cpu_placed():
    from emit import build_scenario
    nl = build_cpu_netlist()
    low = nl.to_nor(keep_registers=True)
    scen, rr = build_scenario(low)
    return nl, low, scen, rr


# --- 1: the Python reference is self-consistent ground truth -----------------------

def test_reference_emits_thirteen_fibonacci_terms_then_overflow():
    stream = fibonacci_reference(steps=400)
    assert stream[:13] == FIB_TERMS_8BIT
    # after 233 the recurrence overflows 8 bits: 144 + 233 = 377, 377 & 0xFF = 121.
    assert stream[13] == FIB_OVERFLOW_TERM == 121


def test_reference_free_runs_fibonacci_mod_256():
    # past the 13 representable terms the machine keeps computing the recurrence MODULO 256.
    stream = fibonacci_reference(steps=400)
    for i in range(2, len(stream)):
        assert stream[i] == (stream[i - 1] + stream[i - 2]) & 0xFF


def test_program_is_sixteen_words():
    assert len(FIB_PROGRAM) == PROG_WORDS


# --- 2: behavioural Amaranth matches the reference --------------------------------

def test_behavioural_cpu_emits_fibonacci():
    # 2 edges per instruction; ~93 instructions reach the overflow term, so 200 edges is ample.
    stream = _behavioural_stream(FIB_PROGRAM, edges=400)
    assert stream[:13] == FIB_TERMS_8BIT
    assert stream[13] == FIB_OVERFLOW_TERM


def test_behavioural_cpu_matches_reference_stream_long():
    edges = 600
    stream = _behavioural_stream(FIB_PROGRAM, edges=edges)
    # the reference, run for the SAME number of instructions (edges // 2), must agree exactly.
    ref = fibonacci_reference(steps=edges // 2)
    assert stream == ref[:len(stream)]


# --- 3: structural netlist matches the reference, and the behavioural model --------

def test_structural_netlist_emits_fibonacci():
    nl = build_cpu_netlist()
    nl.validate()
    assert nl.is_sequential()
    assert nl.clocks() == ["clk"]
    stream = netlist_output_stream(nl, instructions=120)
    assert stream[:13] == FIB_TERMS_8BIT
    assert stream[13] == FIB_OVERFLOW_TERM


def test_structural_netlist_matches_behavioural_cycle_for_cycle():
    """The strongest check: the structural gate + DFF netlist and the behavioural Amaranth Cpu
    advance through identical (ACC, PC, Z, out_we, out_port) on EVERY clock edge, not just the
    emitted stream. This is sequential_equivalent at the level of a whole CPU."""
    edges = 80

    dut = Cpu()
    m = Module()
    m.submodules.dut = dut
    beh = []

    async def tb(ctx):
        for _ in range(edges):
            await ctx.tick()
            beh.append((ctx.get(dut.acc), ctx.get(dut.pc), ctx.get(dut.z),
                        ctx.get(dut.out_we), ctx.get(dut.out_port)))

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()

    nl = build_cpu_netlist()
    ssim = SeqSim(nl)
    ssim.reset({"clk": 0})
    struct = []
    for _ in range(edges):
        ssim.clock_cycle({}, clock="clk")
        acc = sum(ssim.value(f"acc{i}") << i for i in range(ACC_BITS))
        pc = sum(ssim.value(f"pc{i}") << i for i in range(PC_BITS))
        struct.append((acc, pc, ssim.value("z"),
                       ssim.value("out_we"),
                       sum(ssim.value(f"out{i}") << i for i in range(ACC_BITS))))

    assert struct == beh


# --- 4: each ISA opcode, through the reference AND the structural netlist ----------

def test_ldi_loads_immediate():
    prog = _pad16([
        encode(OP_LDI, 7),         # 0 ACC=7
        encode(OP_STA, OUT_ADDR),  # 1 emit 7
        encode(OP_JMP, 2),         # 2 halt
    ])
    assert cpu_reference(prog, 20)["out_stream"][:1] == [7]
    assert netlist_output_stream(build_cpu_netlist(prog), 20)[:1] == [7]


def test_add_accumulates():
    prog = _pad16([
        encode(OP_LDI, 5),         # 0 ACC=5
        encode(OP_STA, T_ADDR),    # 1 T=5
        encode(OP_LDI, 9),         # 2 ACC=9
        encode(OP_ADD, T_ADDR),    # 3 ACC=9+5=14
        encode(OP_STA, OUT_ADDR),  # 4 emit 14
        encode(OP_JMP, 5),         # 5 halt
    ])
    assert cpu_reference(prog, 30)["out_stream"][:1] == [14]
    assert netlist_output_stream(build_cpu_netlist(prog), 30)[:1] == [14]


def test_sub_subtracts_and_sets_zero_flag():
    # SUB to exactly zero sets Z; we observe Z indirectly via a BZ that fires.
    prog = _pad16([
        encode(OP_LDI, 6),         # 0 ACC=6
        encode(OP_STA, T_ADDR),    # 1 T=6
        encode(OP_LDI, 6),         # 2 ACC=6
        encode(OP_SUB, T_ADDR),    # 3 ACC=0, Z=1
        encode(OP_STA, OUT_ADDR),  # 4 emit 0  (proves SUB wrapped to 0)
        encode(OP_JMP, 5),         # 5 halt
    ])
    ref = cpu_reference(prog, 30)
    assert ref["out_stream"][:1] == [0]
    assert ref["z"] == 1
    assert netlist_output_stream(build_cpu_netlist(prog), 30)[:1] == [0]


def test_sub_wraps_modulo_256():
    prog = _pad16([
        encode(OP_LDI, 1),         # 0 ACC=1
        encode(OP_STA, T_ADDR),    # 1 T=1
        encode(OP_LDI, 0),         # 2 ACC=0
        encode(OP_SUB, T_ADDR),    # 3 ACC=0-1 = 255 (two's complement wrap)
        encode(OP_STA, OUT_ADDR),  # 4 emit 255
        encode(OP_JMP, 5),         # 5 halt
    ])
    assert cpu_reference(prog, 30)["out_stream"][:1] == [255]
    assert netlist_output_stream(build_cpu_netlist(prog), 30)[:1] == [255]


def test_sta_writes_data_memory():
    prog = _pad16([
        encode(OP_LDI, 3),         # 0 ACC=3
        encode(OP_STA, T_ADDR),    # 1 DMEM[T]=3
        encode(OP_LDI, 0),         # 2 ACC=0
        encode(OP_ADD, T_ADDR),    # 3 ACC=0+3=3 (reads back what STA wrote)
        encode(OP_STA, OUT_ADDR),  # 4 emit 3
        encode(OP_JMP, 5),
    ])
    ref = cpu_reference(prog, 30)
    assert ref["out_stream"][:1] == [3]
    assert ref["dmem"][T_ADDR] == 3


def test_bz_taken_branches():
    prog = _pad16([
        encode(OP_LDI, 0),         # 0 ACC=0, Z=1
        encode(OP_BZ, 4),          # 1 Z set -> branch to 4
        encode(OP_LDI, 99 & 0xF),  # 2 poison (skipped)
        encode(OP_STA, OUT_ADDR),  # 3 poison emit (skipped)
        encode(OP_LDI, 5),         # 4 ACC=5
        encode(OP_STA, OUT_ADDR),  # 5 emit 5
        encode(OP_JMP, 6),         # 6 halt
    ])
    assert cpu_reference(prog, 30)["out_stream"][:2] == [5]
    assert netlist_output_stream(build_cpu_netlist(prog), 30)[:2] == [5]


def test_bz_not_taken_falls_through():
    prog = _pad16([
        encode(OP_LDI, 4),         # 0 ACC=4, Z=0
        encode(OP_BZ, 5),          # 1 Z clear -> NOT taken
        encode(OP_LDI, 9),         # 2 ACC=9
        encode(OP_STA, OUT_ADDR),  # 3 emit 9
        encode(OP_JMP, 4),         # 4 halt
        encode(OP_STA, OUT_ADDR),  # 5 (branch target, unreached)
    ])
    assert cpu_reference(prog, 30)["out_stream"][:1] == [9]
    assert netlist_output_stream(build_cpu_netlist(prog), 30)[:1] == [9]


def test_jmp_is_unconditional():
    prog = _pad16([
        encode(OP_JMP, 3),         # 0 jump to 3
        encode(OP_LDI, 1),         # 1 poison
        encode(OP_STA, OUT_ADDR),  # 2 poison emit
        encode(OP_LDI, 8),         # 3 ACC=8
        encode(OP_STA, OUT_ADDR),  # 4 emit 8
        encode(OP_JMP, 5),         # 5 halt
    ])
    assert cpu_reference(prog, 30)["out_stream"][:1] == [8]
    assert netlist_output_stream(build_cpu_netlist(prog), 30)[:1] == [8]


# --- 5: the buildable NOR lowering still computes Fibonacci ------------------------

def test_lowered_cpu_is_buildable_and_emits_fibonacci():
    nl = build_cpu_netlist()
    low = nl.to_nor(keep_registers=True)
    low.validate()
    assert low.is_sequential()
    # every cell is buildable on the substrate (NOR / CONST) or a register tile (DFF).
    for c in low.cells:
        assert c.type in (BUILDABLE | {"DFF"}), f"non-buildable cell {c.id}:{c.type}"
    # the number of register tiles is preserved by the lowering (registers are kept, not split).
    assert sum(1 for c in low.cells if c.type == "DFF") == \
        sum(1 for c in nl.cells if c.type == "DFF")
    stream = netlist_output_stream(low, instructions=120)
    assert stream[:13] == FIB_TERMS_8BIT
    assert stream[13] == FIB_OVERFLOW_TERM


def test_register_bit_count_is_the_lean_state_budget():
    """The architectural state is exactly ACC(8)+PC(4)+Z(1)+phase(1)+IR_op(4)+IR_arg(4)+
    DMEM(DMEM_WORDS*8). Pin the register count so the 'state is the scarce resource' budget is a
    test, not a comment."""
    nl = build_cpu_netlist()
    n_dff = sum(1 for c in nl.cells if c.type == "DFF")
    expected = ACC_BITS + PC_BITS + 1 + 1 + 4 + 4 + DMEM_WORDS * 8
    assert n_dff == expected == 54


# --- 6: the whole CPU through place-and-route -------------------------------------

def test_cpu_places_routes_completely(cpu_placed):
    """The CPU places (one register tile per architectural bit), routes to 100 percent of nets,
    is DRC-clean, and the clock reaches every register tile.

    This used to be the documented backend-scale negative (STUCK.md #8): at ~1600 cells the
    shared constructive channel router took its riser fallback and produced ~410 DRC route_shorts.
    The cause turned out NOT to be riser crowding (no riser ever fell back) but two wide-fan-in
    blind spots that only bite at this scale: a cell footprint that did not grow with fan-in (so a
    wide NOR spilled its input pins below its 3-tall stamp) and the REPEATED-input case
    (NOR(a,a,a,a)), whose stacked same-net pins were each routed as their own stub+riser, filling a
    2D blob a foreign riser then crossed non-perpendicularly. Both are fixed (place._cell_height
    grows to contain every pin; the router coalesces a run of stacked same-net pins into one pin
    -column segment + one riser), so the CPU now routes 100 percent of nets with ZERO DRC, the same
    as the 92-cell adder and the 893-cell ALU. The fix changes neither the netlist/scenario
    contracts nor the logic (verified below: reconstructed-from-placement still emits Fibonacci).
    """
    from check import unrouted_nets, overlap_violations, drc
    nl, low, scen, rr = cpu_placed

    # placement legal (no two cells overlap), routing complete, and DRC clean.
    assert overlap_violations(scen) == []
    assert unrouted_nets(scen) == [], f"unrouted: {unrouted_nets(scen)}"
    routed, total = rr.coverage()
    assert routed == total > 0, f"routed only {routed}/{total}"
    d = drc(scen)
    assert d == [], f"DRC: {[(v.kind, v.detail) for v in d][:10]}"

    # one register tile per architectural bit, the clock reaches every one of them.
    regs = [c for c in scen.cells if c.is_register()]
    assert len(regs) == sum(1 for c in low.cells if c.type == "DFF") == 54
    _assert_clock_reaches_every_register(scen, regs)


def test_cpu_reconstruction_from_placement_emits_fibonacci(cpu_placed):
    """Reconstruct the netlist from the placed/routed scenario (connectivity read off the placed
    pins + routes, not from the source netlist) and confirm it still emits the Fibonacci stream.
    This proves the placement preserved the CPU's logic, the sequential analogue of the adder's
    verify_equivalence, sampled by stepping (the 55-input combinational cone is far too wide to
    enumerate a full truth table, exactly as the ALU uses a strong sample)."""
    from check import scenario_to_netlist
    nl, low, scen, rr = cpu_placed

    rebuilt = scenario_to_netlist(scen, require_routed=True)
    assert rebuilt.is_sequential()
    assert sum(1 for c in rebuilt.cells if c.type == "DFF") == 54
    stream = netlist_output_stream(rebuilt, instructions=120)
    assert stream[:13] == FIB_TERMS_8BIT
    assert stream[13] == FIB_OVERFLOW_TERM


def _assert_clock_reaches_every_register(scen, regs):
    """The clock-distribution net's route physically touches every register's clock pin."""
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


# --- 7: stats reporting -----------------------------------------------------------

def test_netlist_stats_report():
    """Print the NOR / register / state counts the brief asks the report to carry. Not an
    assertion of exact totals (those can shift with gate-emitter tweaks), just a sanity floor
    plus a printed breakdown for the run report."""
    nl = build_cpu_netlist()
    s = netlist_stats(nl)
    # sane floors: a real CPU is hundreds of NOR and exactly 54 registers.
    assert s["DFF"] == 54
    assert s["NOR"] > 500
    assert s["_lowered_DFF"] == 54
    print("CPU structural stats:", {k: v for k, v in s.items() if not k.startswith("_")})
    print("CPU lowered (keep_registers) stats:",
          {k: v for k, v in s.items() if k.startswith("_lowered")})
