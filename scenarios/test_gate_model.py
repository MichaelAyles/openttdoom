"""Tests for the INTENDED clocked NOR/NOT semantics in gate_model.py.

These tests check that the Python model reproduces the NOR and NOT truth tables
when driven across clock cycles, and that it shows the one-edge register latency
we designed for. They do NOT prove OpenTTD realises this. They pin down the
contract the eventual train-and-signal construction must meet. See
scenarios/GATE_DESIGN.md for the construction and STUCK.md for what is unverified.
"""

from itertools import product

import pytest

from gate_model import (
    ClockedNetwork,
    NorTile,
    nor,
    single_nor,
    single_not,
)


# --- the pure combinational primitive --------------------------------------

@pytest.mark.parametrize("bits,expected", [
    ((0,), 1),
    ((1,), 0),
    ((0, 0), 1),
    ((0, 1), 0),
    ((1, 0), 0),
    ((1, 1), 0),
    ((0, 0, 0), 1),
    ((0, 0, 1), 0),
])
def test_nor_primitive(bits, expected):
    assert nor(bits) == expected


# --- one NOR tile reproduces the NOR truth table over clock cycles ---------

def test_single_nor_truth_table_2in():
    net = single_nor(2)
    for a, b in product((0, 1), repeat=2):
        net.reset({"a": a, "b": b})
        # one edge to sample the held inputs and latch the result.
        net.step()
        assert net.value("y") == nor((a, b)), f"a={a} b={b}"


def test_single_nor_truth_table_3in():
    net = single_nor(3)
    ins = ["a", "b", "c"]
    for combo in product((0, 1), repeat=3):
        net.reset(dict(zip(ins, combo)))
        net.step()
        assert net.value("y") == nor(combo), f"in={combo}"


def test_single_not_truth_table():
    # NOT is a one-input NOR tile.
    net = single_not()
    for a in (0, 1):
        net.reset({"a": a})
        net.step()
        assert net.value("y") == (1 - a), f"a={a}"


# --- the registered latency: output reflects LAST edge's inputs ------------

def test_one_edge_latency():
    """Driving a new input mid-run only affects the output one edge later."""
    net = single_nor(2)
    net.reset({"a": 0, "b": 0})
    net.step()
    assert net.value("y") == 1            # NOR(0,0) = 1

    # change an input. Output must NOT change until the next edge.
    net.drive({"a": 1})
    assert net.value("y") == 1            # still the old latched value
    net.step()
    assert net.value("y") == 0            # NOR(1,0) = 0, now visible

    net.drive({"a": 0})
    assert net.value("y") == 0            # old value held for one more edge
    net.step()
    assert net.value("y") == 1            # NOR(0,0) = 1 again


def test_output_holds_when_inputs_stable():
    net = single_nor(2)
    net.reset({"a": 1, "b": 0})
    net.step()
    first = net.value("y")
    # extra edges with no input change must keep the same output.
    for _ in range(5):
        net.step()
        assert net.value("y") == first


# --- a two-tile chain: NOT of NOR, to check propagation across tiles -------

def test_two_tile_chain_propagates_one_edge_per_tile():
    """y = NOR(a,b); z = NOT(y). z settles two edges after inputs are set,
    one edge per tile, which is the registered-pipeline behaviour."""
    g0 = NorTile(name="g0", inputs=["a", "b"], output="y")
    g1 = NorTile(name="g1", inputs=["y"], output="z")
    net = ClockedNetwork(tiles=[g0, g1], primary_inputs=["a", "b"])

    for a, b in product((0, 1), repeat=2):
        net.reset({"a": a, "b": b})
        # settle() steps until nothing changes; for a depth-2 chain that is a
        # small fixed number of edges.
        net.settle(max_cycles=16)
        expected_y = nor((a, b))
        expected_z = 1 - expected_y      # NOT(y)
        assert net.value("y") == expected_y, f"y a={a} b={b}"
        assert net.value("z") == expected_z, f"z a={a} b={b}"


def test_chain_latency_is_one_edge_per_tile():
    g0 = NorTile(name="g0", inputs=["a"], output="y")     # y = NOT a
    g1 = NorTile(name="g1", inputs=["y"], output="z")     # z = NOT y = a
    net = ClockedNetwork(tiles=[g0, g1], primary_inputs=["a"])
    net.reset({"a": 0})
    net.settle()
    assert net.value("z") == 0

    net.drive({"a": 1})
    net.step()                           # edge 1: g0 sees a=1 -> y will be 0
    # z still reflects old y, so a is not through yet.
    assert net.value("z") == 0
    net.step()                           # edge 2: g1 sees new y -> z = 1
    assert net.value("z") == 1


def test_settle_raises_on_oscillator():
    """A one-tile feedback inverter (y = NOT y) can never settle and must raise,
    proving settle() does not silently accept a non-converging design."""
    g = NorTile(name="g", inputs=["y"], output="y")
    net = ClockedNetwork(tiles=[g], primary_inputs=[])
    net.reset({})
    with pytest.raises(RuntimeError):
        net.settle(max_cycles=8)
