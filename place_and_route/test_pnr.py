"""Tests for the openttdoom M3 place-and-route backend.

Builds small sample netlists with netlist.NetlistBuilder (a 1-bit full adder and a 2-bit
ripple-carry adder), runs them through build_scenario, and checks the three properties that
matter for M3:

  1. DRC finds no cell/cell footprint overlaps (placement is physically legal).
  2. The committed routes never short two signals (no route/route tile sharing).
  3. The scenario reconstructs to a netlist logically equivalent to the source: same primary
     I/O and identical exhaustive truth table. This reconstruction reads the placed cells and
     routes back out of the scenario, it does not echo the source netlist.

Routing is the constructive channel router (channel_route.py): it reaches 100 percent routed
on the ripple adders by laying each net on a unique horizontal trunk row, connecting pins with
unique-column vertical risers, and crossing other nets only as legal perpendicular bridges.
So the adder tests demand FULL routing (unrouted == [] and zero DRC violations), and there are
dedicated tests that a genuine same-direction overlap is still flagged route_short while a
marked perpendicular bridge passes.

Run just this file:  python -m pytest place_and_route/test_pnr.py -q
"""

from __future__ import annotations

import os

from netlist import NetlistBuilder, Netlist
from scenario import Scenario, Route
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

def _assert_complete(nl: Netlist):
    """Place + route nl and assert it routes COMPLETELY: every net connected, DRC clean,
    logic preserved under strict (require_routed) equivalence. Returns (scen, rr)."""
    scen, rr = build_scenario(nl)
    assert overlap_violations(scen) == []
    assert drc(scen) == [], f"DRC violations: {[(v.kind, v.detail) for v in drc(scen)]}"
    assert unrouted_nets(scen) == [], f"unrouted: {unrouted_nets(scen)}"
    assert verify_equivalence(nl, scen, require_routed=True) is True
    routed, total = rr.coverage()
    assert routed == total, f"routed only {routed}/{total}"
    return scen, rr


def test_one_bit_adder_routes_completely():
    # The 1-bit full adder routes COMPLETELY: every net connected, DRC clean, strict equiv.
    _assert_complete(full_adder_1bit())


def test_two_bit_ripple_adder_routes_completely():
    _assert_complete(ripple_adder(2))


def test_four_bit_ripple_adder_routes_completely():
    # The de-risking milestone: the 4-bit ripple adder, which the old maze router could not
    # fully route (not planar), now routes 100 percent via perpendicular bridge crossings.
    scen, rr = _assert_complete(ripple_adder(4))
    # bridges are actually used (the netlist is not planar), and every bridge is on a real
    # perpendicular crossing (drc would have flagged a stale marker).
    total_bridges = sum(len(r.bridges) for r in scen.routes)
    assert total_bridges > 0, "expected perpendicular bridge crossings in a 4-bit adder"


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


# --- bridge / crossing DRC rule --------------------------------------------------

def _crossing_scenario(mark_bridge: bool, parallel: bool = False) -> Scenario:
    """A tiny 2-route scenario with one shared tile, for the bridge DRC tests.

    Net "h" runs horizontally across row 5 (x = 1..9); net "v" runs vertically down column 5
    (y = 1..9). They meet at the single tile (5, 5): a clean perpendicular crossing. If
    mark_bridge, net "h" (the horizontal one carried over) records (5,5) in its bridges, which
    must make the crossing legal. If not, the unmarked crossing must be flagged route_short.

    With parallel=True, net "v" is instead laid HORIZONTALLY on row 5 overlapping "h" at (5,5),
    so the shared tile is a genuine same-direction overlap, which must always be route_short
    regardless of any bridge marker. No cells or pads, so the only possible violation is the
    tile-sharing rule under test.
    """
    h_path = [(x, 5) for x in range(1, 10)]
    if parallel:
        v_path = [(x, 5) for x in range(3, 8)]      # parallel run on the SAME row 5
    else:
        v_path = [(5, y) for y in range(1, 10)]      # perpendicular vertical through (5,5)
    h = Route(net="h", path=h_path, bridges=([(5, 5)] if mark_bridge else []))
    v = Route(net="v", path=v_path)
    return Scenario(name="crossing", map_x=64, map_y=64, routes=[h, v])


def test_perpendicular_bridge_passes_drc_unmarked_crossing_flagged():
    # A perpendicular crossing marked as a bridge passes DRC; the SAME crossing NOT marked is
    # flagged route_short. This is the core of the model change.
    ok = _crossing_scenario(mark_bridge=True)
    assert [v for v in drc(ok) if v.kind == "route_short"] == [], \
        f"marked bridge should pass: {[v.detail for v in drc(ok)]}"

    bad = _crossing_scenario(mark_bridge=False)
    shorts = [v for v in drc(bad) if v.kind == "route_short"]
    assert len(shorts) == 1, f"unmarked crossing must be flagged: {[v.detail for v in drc(bad)]}"
    assert "(5, 5)" in shorts[0].detail


def test_same_direction_overlap_still_route_short():
    # A genuine same-direction overlap (two parallel segments of different nets on one tile,
    # NOT a perpendicular bridge) is STILL flagged route_short, even if marked as a bridge.
    overlap = _crossing_scenario(mark_bridge=False, parallel=True)
    shorts = [v for v in drc(overlap) if v.kind == "route_short"]
    assert shorts, "parallel same-direction overlap must be route_short"

    # marking the overlapped tile as a bridge must NOT launder a same-direction short.
    overlap_marked = _crossing_scenario(mark_bridge=True, parallel=True)
    shorts_marked = [v for v in drc(overlap_marked) if v.kind == "route_short"]
    assert shorts_marked, "a bridge marker cannot make a same-direction overlap legal"


def test_bridges_survive_json_roundtrip():
    # The new Route.bridges field serialises and reloads, and old JSON without it still loads
    # (defaults to no bridges). A real routed scenario carries bridges through to_json/from_dict.
    nl = ripple_adder(2)
    scen, _ = build_scenario(nl)
    assert sum(len(r.bridges) for r in scen.routes) > 0, "expected bridges in a 2-bit adder"

    import json
    scen2 = Scenario.from_dict(json.loads(scen.to_json()))
    before = {r.net: sorted(r.bridges) for r in scen.routes}
    after = {r.net: sorted(r.bridges) for r in scen2.routes}
    assert before == after, "bridges must round-trip through JSON unchanged"
    assert drc(scen2) == [], "reloaded scenario must still pass DRC"

    # old JSON missing the bridges field still loads (backward compatible).
    legacy = json.loads(scen.to_json())
    for r in legacy["routes"]:
        r.pop("bridges", None)
    scen3 = Scenario.from_dict(legacy)
    assert all(r.bridges == [] for r in scen3.routes)
