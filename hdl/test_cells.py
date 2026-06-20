"""Tests for the primitive Amaranth cells in cells.py.

Run only this file (other modules are built concurrently):
    python -m pytest hdl/test_cells.py -q

These cells mirror the substrate gate set. They are pure combinational, so we just
simulate each one with amaranth.sim over its full input space and assert the truth
table. The point is to exercise the primitives the structural adder documents but does
not itself instantiate.
"""

from __future__ import annotations

from amaranth.hdl import Module
from amaranth.sim import Simulator

from cells import Nor, Xor2


def _sim_truth_table(dut, inputs, output, vectors):
    """Drive dut over every row of vectors and return {input_tuple: out_bit}.

    inputs is the ordered list of input Signals, output is the output Signal, and
    vectors is an iterable of input value tuples (one value per input Signal).
    """
    m = Module()
    m.submodules.dut = dut

    results: dict[tuple[int, ...], int] = {}

    async def testbench(ctx):
        for row in vectors:
            for sig, val in zip(inputs, row):
                ctx.set(sig, val)
            await ctx.delay(1e-6)
            results[tuple(row)] = ctx.get(output)

    sim = Simulator(m)
    sim.add_testbench(testbench)
    sim.run()
    return results


def test_nor_width1_is_inverter():
    dut = Nor(width=1)
    tt = _sim_truth_table(dut, dut.inputs, dut.out, [(0,), (1,)])
    assert tt == {(0,): 1, (1,): 0}


def test_nor_width2_truth_table():
    dut = Nor(width=2)
    vectors = [(0, 0), (0, 1), (1, 0), (1, 1)]
    tt = _sim_truth_table(dut, dut.inputs, dut.out, vectors)
    # out = NOT(a OR b): high only when both inputs are low.
    assert tt == {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0}


def test_xor2_truth_table():
    dut = Xor2()
    vectors = [(0, 0), (0, 1), (1, 0), (1, 1)]
    tt = _sim_truth_table(dut, [dut.a, dut.b], dut.out, vectors)
    # out = a XOR b: high when the inputs differ.
    assert tt == {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}
