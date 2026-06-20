"""Tests for the openttdoom M3 place-and-route backend.

Builds small sample netlists with netlist.NetlistBuilder (a 1-bit full adder and a 2-bit
ripple-carry adder), runs them through build_scenario, and checks the three properties that
matter for M3:

  1. DRC finds no cell/cell footprint overlaps (placement is physically legal).
  2. The committed routes never short two signals (no route/route tile sharing).
  3. The scenario reconstructs to a netlist logically equivalent to the source: same primary
     I/O and identical exhaustive truth table. This reconstruction reads the placed cells and
     routes back out of the scenario, it does not echo the source netlist.

Routing is crude (see route.py): it does not always reach 100 percent routed on congested
designs, so the tests report routed-net coverage and assert it is substantial rather than
demanding full routing. Unrouted nets are recorded honestly by the router and surfaced here.

Run just this file:  python -m pytest place_and_route/test_pnr.py -q
"""

from __future__ import annotations

import os

from netlist import NetlistBuilder, Netlist
from scenario import Scenario
from emit import build_scenario
from check import (drc, overlap_violations, scenario_to_netlist,
                   verify_equivalence, unrouted_nets)


# --- sample netlists -------------------------------------------------------------

def full_adder_1bit() -> Netlist:
    """1-bit full adder: sum = a ^ b ^ cin, cout = ab + cin(a ^ b). NOR-lowered."""
    b = NetlistBuilder("full_adder_1bit")
    a = b.declare_input("a")
    bb = b.declare_input("b")
    cin = b.declare_input("cin")
    axb = b.xor2(a, bb)
    b.alias_output("sum", b.xor2(axb, cin))
    b.alias_output("cout", b.or_([b.and_([a, bb]), b.and_([axb, cin])]))
    return b.finish()


def ripple_adder(bits: int) -> Netlist:
    """`bits`-bit ripple-carry adder, carry chained through full adders. NOR-lowered."""
    b = NetlistBuilder(f"ripple_adder_{bits}b")
    a = [b.declare_input(f"a{i}") for i in range(bits)]
    bb = [b.declare_input(f"b{i}") for i in range(bits)]
    carry = b.const0()
    for i in range(bits):
        axb = b.xor2(a[i], bb[i])
        b.alias_output(f"s{i}", b.xor2(axb, carry))
        carry = b.or_([b.and_([a[i], bb[i]]), b.and_([axb, carry])])
    b.alias_output("cout", carry)
    return b.finish()


def wide_nor_netlist(fanin: int = 5) -> Netlist:
    """A netlist whose single cell is a NOR with `fanin` (>=4) inputs.

    NOR is unbounded fan-in, so this exercises the wide-cell footprint sizing: with more
    inputs than the baseline CELL_H tiles, every input pin must still land on a distinct
    tile (no pin collision). The output is a double inversion (alias_output) so the wide
    NOR's net survives lowering and the primary output names it.
    """
    b = NetlistBuilder(f"wide_nor_{fanin}")
    ins = [b.declare_input(f"i{i}") for i in range(fanin)]
    b.alias_output("y", b.nor(ins))
    return b.finish()


# --- tests -----------------------------------------------------------------------

def test_full_adder_placement_legal_and_equivalent():
    nl = full_adder_1bit()
    scen, rr = build_scenario(nl)

    # 1. DRC is clean: no footprint overlap, off-map, route-cuts-cell/pad, or route shorts.
    assert overlap_violations(scen) == []
    assert drc(scen) == [], f"DRC violations: {[v.kind for v in drc(scen)]}"

    # 2. the reconstructed netlist is logically equivalent to the source.
    assert verify_equivalence(nl, scen) is True

    # routing is crude; report coverage and require it is substantial.
    routed, total = rr.coverage()
    assert routed >= int(0.8 * total), f"routed only {routed}/{total}"


def test_two_bit_ripple_adder_placement_legal_and_equivalent():
    nl = ripple_adder(2)
    scen, rr = build_scenario(nl)

    assert overlap_violations(scen) == []
    # no shorts: the committed routes are tile-disjoint even when some nets are unrouted.
    assert [v for v in drc(scen) if v.kind == "route_short"] == []
    assert verify_equivalence(nl, scen) is True

    routed, total = rr.coverage()
    # multi-bit adders are congested; the crude router still routes the bulk of nets.
    assert routed >= int(0.6 * total), f"routed only {routed}/{total}"


def test_reconstruction_reads_from_scenario_not_source():
    # A scenario whose route is tampered to connect the wrong tiles must be rejected, proving
    # scenario_to_netlist actually follows the routes rather than trusting names blindly.
    nl = full_adder_1bit()
    scen, _ = build_scenario(nl)
    assert scen.routes, "expected at least one route"
    scen.routes[0].path = [(9999, 9999), (9998, 9998)]  # disconnected garbage
    try:
        scenario_to_netlist(scen)
        assert False, "expected a mis-wired route to be rejected"
    except ValueError as e:
        assert "wrong pins" in str(e)


def test_strict_routed_equivalence_flags_unrouted():
    # With require_routed=True, equivalence holds only if every net is physically routed.
    # If the crude router leaves nets unrouted, strict mode must raise (honest, not faked).
    nl = ripple_adder(2)
    scen, rr = build_scenario(nl)
    routed, total = rr.coverage()
    if routed == total:
        assert verify_equivalence(nl, scen, require_routed=True) is True
    else:
        try:
            verify_equivalence(nl, scen, require_routed=True)
            assert False, "expected strict mode to raise on an unrouted net"
        except ValueError as e:
            assert "do not connect" in str(e)
    # logical equivalence (the meaningful correctness property) holds regardless.
    assert verify_equivalence(nl, scen, require_routed=False) is True


def test_scenario_json_roundtrip_reconstructs():
    nl = full_adder_1bit()
    scen, _ = build_scenario(nl)
    blob = scen.to_json()
    scen2 = Scenario.from_dict(__import__("json").loads(blob))
    assert verify_equivalence(nl, scen2) is True


def test_write_example_scenario(tmp_path=None):
    # Emit the canonical example to scenarios/ as both JSON and .nut, and confirm it loads
    # back and reconstructs to the source logic. This doubles as the saved sample artifact.
    nl = full_adder_1bit()
    scen, rr = build_scenario(nl)

    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "scenarios")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "example.scenario.json")
    nut_path = os.path.join(out_dir, "example.scenario.nut")

    scen.save(json_path)
    with open(nut_path, "w") as f:
        f.write(scen.to_nut())

    assert os.path.exists(json_path)
    assert os.path.exists(nut_path)

    reloaded = Scenario.load(json_path)
    assert verify_equivalence(nl, reloaded) is True

    # the .nut is a non-empty Squirrel data table the GameScript reads.
    with open(nut_path) as f:
        nut = f.read()
    assert "GetScenarioData" in nut
    assert len(nut) > 0


def test_wide_nor_pins_on_distinct_tiles_no_collision():
    # A wide NOR (>=4 inputs) must give every input pin its own tile: stacking two nets on
    # one tile is a short. The footprint grows with fan-in (place._cell_height), and the
    # pin_collision DRC check flags any tile holding two different nets.
    nl = wide_nor_netlist(5)
    scen, _ = build_scenario(nl)

    # no pin collisions (and the placement is otherwise legal).
    assert [v for v in drc(scen) if v.kind == "pin_collision"] == []
    assert drc(scen) == [], f"DRC violations: {[(v.kind, v.detail) for v in drc(scen)]}"

    # the wide NOR's input pins each sit on a DISTINCT tile.
    nor_cells = [c for c in scen.cells if len(c.inputs) >= 4]
    assert nor_cells, "expected a wide (>=4 input) cell in the placement"
    for c in nor_cells:
        tiles = [(p.x, p.y) for p in c.inputs]
        assert len(set(tiles)) == len(tiles), (
            f"cell {c.id} input pins share tiles: {tiles}")
        # the output pin is on its own tile too, clear of every input pin.
        assert (c.output.x, c.output.y) not in set(tiles)

    # logic still reconstructs correctly.
    assert verify_equivalence(nl, scen) is True


def test_truncated_output_route_is_flagged():
    # An output route that stops short of its framebuffer/output pad must be reported as
    # unrouted (output pads are consumers, same as input pads are sources). Before the fix
    # such a route passed as fully connected.
    nl = full_adder_1bit()
    scen, _ = build_scenario(nl)

    out_pads = {p.net: (p.x, p.y) for p in scen.output_pads()}
    assert out_pads, "expected output pads"

    # find an output net whose route currently reaches its pad, then drop the pad tile.
    tampered = None
    for r in scen.routes:
        if r.net in out_pads and out_pads[r.net] in r.path:
            r.path = [t for t in r.path if t != out_pads[r.net]]
            tampered = r.net
            break
    assert tampered is not None, "expected a routed output net to truncate"

    # the truncated output net is now reported unrouted (it no longer reaches its pad).
    assert tampered in unrouted_nets(scen)

    # and reconstruction rejects it: a route present but not reaching its named pad is a
    # wrong-pins connection, fatal even without require_routed.
    try:
        scenario_to_netlist(scen)
        assert False, "expected a truncated output route to be rejected"
    except ValueError as e:
        assert "wrong pins" in str(e)
