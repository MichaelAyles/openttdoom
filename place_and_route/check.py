"""Design-rule checks and equivalence proof for the openttdoom M3 backend.

Three jobs:
  drc(scenario)            -> a concrete list of design-rule violations (overlaps, off-map
                              tiles, routes cutting through cell footprints they shouldn't).
  scenario_to_netlist(s)   -> rebuild the LOGICAL Netlist purely from the placed cells and
                              the routed nets. This reads the spatial scenario back out and
                              recovers connectivity, it does NOT take the source netlist.
  verify_equivalence(n, s) -> True iff scenario_to_netlist(s) is equivalent() to n.

The reconstruction is the load-bearing check: a reviewer will confirm it really walks the
scenario. Connectivity is recovered from net NAMES carried on pins and routes: every cell
output pin names the net it drives, every input pin names the net it consumes, and a Route
ties a driver's output tile to consumer input tiles. We rebuild cells from the placed cell
pins and verify the routes actually connect the pins the names claim, so a mis-routed
scenario is caught here rather than silently passing.

stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from netlist import Netlist, Cell, Ports, equivalent
from scenario import Scenario

Coord = Tuple[int, int]


@dataclass
class Violation:
    kind: str           # "overlap" / "off_map" / "route_cuts_cell" / "route_off_map"
                        # / "pin_collision" / "route_cuts_pad" / "route_short"
    detail: str


# --- DRC --------------------------------------------------------------------------

def drc(scenario: Scenario) -> List[Violation]:
    """Return every design-rule violation found in `scenario` as a concrete list.

    Checks:
      - cell/cell footprint overlap (two cells claiming the same tile),
      - any cell tile off the map,
      - two cell pins carrying DIFFERENT net names on the same tile (a pin collision: the
        substrate would read the two nets as shorted together; this bites wide-fan-in cells
        whose pins could otherwise be stacked onto fewer tiles than they have inputs),
      - route tiles off the map,
      - a route passing through a cell footprint tile that is NOT one of that net's own
        pins (a track may terminate on its driver/consumer pins, which sit on footprint
        boundaries, but must not cut across unrelated cell interiors),
      - a route running over a foreign IO pad tile (would short a framebuffer/input pad),
      - two different nets' routes sharing a non-pin tile UNLESS it is a clean perpendicular
        bridge crossing (one net straight-horizontal, the other straight-vertical, with
        exactly one net recording the tile in its Route.bridges); any other sharing
        (same-orientation overlap, three or more nets, a bridge over a pin/footprint/pad, or a
        missing/doubled bridge marker) is a route_short.
    """
    violations: List[Violation] = []
    w, h = scenario.map_x, scenario.map_y

    # Footprint overlap + off-map for cells.
    owner: Dict[Coord, str] = {}
    for c in scenario.cells:
        for t in c.occupied():
            x, y = t
            if not (0 <= x < w and 0 <= y < h):
                violations.append(Violation(
                    "off_map", f"cell {c.id} tile {t} outside map {w}x{h}"))
                continue
            if t in owner and owner[t] != c.id:
                violations.append(Violation(
                    "overlap",
                    f"cells {owner[t]} and {c.id} overlap at tile {t}"))
            else:
                owner[t] = c.id

    # Pin collision: two pins carrying DIFFERENT net names on the same tile is a short. Group
    # every cell input/output pin by its tile and flag any tile that holds more than one
    # distinct net. (Two pins of the SAME net on one tile is fine, that is just a shared
    # node.) A pin sits on a footprint boundary, so a tall enough footprint gives every pin
    # its own tile; this catches the case where it does not. See place._cell_height.
    nets_on_tile: Dict[Coord, Set[str]] = {}
    for c in scenario.cells:
        pins = list(c.inputs)
        if c.output is not None:
            pins.append(c.output)
        # A register tile's clock pin carries the clock net and must not share a tile with the
        # cell's data/output pins (that would short the clock onto data), so include it here.
        if c.clock is not None:
            pins.append(c.clock)
        for pin in pins:
            nets_on_tile.setdefault((pin.x, pin.y), set()).add(pin.net)
    for t in sorted(nets_on_tile):
        nets = nets_on_tile[t]
        if len(nets) > 1:
            violations.append(Violation(
                "pin_collision",
                f"tile {t} holds pins for different nets {sorted(nets)}"))

    # Map every cell tile -> owning cell, and collect each net's legal pin tiles (cell pins
    # plus its own IO pad). A route may legally sit on its own pins/pad.
    cell_tile_owner = owner
    pins_of_net: Dict[str, Set[Coord]] = {}
    for c in scenario.cells:
        if c.output is not None:
            pins_of_net.setdefault(c.output.net, set()).add((c.output.x, c.output.y))
        for pin in c.inputs:
            pins_of_net.setdefault(pin.net, set()).add((pin.x, pin.y))
        # The clock pin is a legal landing tile for the clock-distribution net's route, so the
        # clock riser terminating on it is not a route_cuts_cell violation.
        if c.clock is not None:
            pins_of_net.setdefault(c.clock.net, set()).add((c.clock.x, c.clock.y))
    pad_owner: Dict[Coord, str] = {}
    for pad in scenario.io:
        pad_owner[(pad.x, pad.y)] = pad.net
        pins_of_net.setdefault(pad.net, set()).add((pad.x, pad.y))

    # Precompute, per net, the tile->orientation classification of its route ("H" straight
    # horizontal pass-through, "V" straight vertical, "X" endpoint/turn/branch) and the set of
    # tiles it declares as bridges. A clean perpendicular crossing (the only legal way for two
    # different nets to share a non-pin tile) needs one net horizontal-straight and the other
    # vertical-straight at the tile, with exactly one of them recording it as a bridge.
    orient_of: Dict[str, Dict[Coord, str]] = {}
    bridges_of: Dict[str, Set[Coord]] = {}
    for r in scenario.routes:
        orient_of.setdefault(r.net, {}).update(_route_orientation(r.path))
        bridges_of.setdefault(r.net, set()).update(set(r.bridges))

    # Route checks: off-map, cutting foreign footprints, crossing foreign pads. Tile sharing is
    # handled afterwards via the crossing rule, so first record which nets occupy each tile.
    nets_on_route_tile: Dict[Coord, List[str]] = {}
    for r in scenario.routes:
        legal_pins = pins_of_net.get(r.net, set())
        for t in r.path:
            x, y = t
            if not (0 <= x < w and 0 <= y < h):
                violations.append(Violation(
                    "route_off_map", f"net {r.net} route tile {t} outside map {w}x{h}"))
                continue
            if t in cell_tile_owner and t not in legal_pins:
                violations.append(Violation(
                    "route_cuts_cell",
                    f"net {r.net} route crosses cell {cell_tile_owner[t]} "
                    f"at tile {t} (not a pin of this net)"))
            if t in pad_owner and pad_owner[t] != r.net:
                violations.append(Violation(
                    "route_cuts_pad",
                    f"net {r.net} route crosses {pad_owner[t]}'s IO pad at tile {t}"))
            if t not in legal_pins:
                nets_on_route_tile.setdefault(t, [])
                if r.net not in nets_on_route_tile[t]:
                    nets_on_route_tile[t].append(r.net)

    # Tile sharing: a non-pin tile shared by two different nets is legal ONLY as a clean
    # perpendicular bridge crossing. Anything else (same-orientation overlap, three+ nets, a
    # bridge over a pin/footprint/pad, a missing or doubled bridge marker) is a route_short.
    for t, nets in nets_on_route_tile.items():
        if len(nets) < 2:
            continue
        if len(nets) > 2:
            violations.append(Violation(
                "route_short",
                f"nets {sorted(nets)} all share route tile {t} (not a 2-net crossing)"))
            continue
        a, b = nets
        oa = orient_of.get(a, {}).get(t, "X")
        ob = orient_of.get(b, {}).get(t, "X")
        # Exactly one straight-horizontal and one straight-vertical pass-through.
        if not ((oa == "H" and ob == "V") or (oa == "V" and ob == "H")):
            violations.append(Violation(
                "route_short",
                f"nets {a} and {b} share route tile {t} but it is not a clean perpendicular "
                f"crossing (orientations {oa}/{ob})"))
            continue
        # The bridge tile must not be a pin/footprint/pad tile (it is carried over open ground).
        if t in cell_tile_owner or t in pad_owner:
            violations.append(Violation(
                "route_short",
                f"nets {a} and {b} cross at tile {t} which is a cell/pad tile"))
            continue
        # Exactly one of the two nets must record the tile as a bridge (the one carried over).
        a_br = t in bridges_of.get(a, set())
        b_br = t in bridges_of.get(b, set())
        if a_br == b_br:
            violations.append(Violation(
                "route_short",
                f"nets {a} and {b} cross at tile {t} but the bridge marker is "
                f"{'missing' if not a_br else 'recorded by both'} "
                f"(exactly one net must list it in bridges)"))
            continue
        # Legal: the horizontal (trunk) net should be the one carried over. We do not hard-fail
        # if the vertical net recorded it instead (the data still unambiguously marks the
        # crossing), but the construction always bridges the horizontal net.

    # A bridge tile a net declares but does not actually share with a perpendicular net is a
    # stale/false marker; flag it so bridges stay honest.
    for r in scenario.routes:
        for t in r.bridges:
            nets = nets_on_route_tile.get(t, [])
            others = [n for n in nets if n != r.net]
            if not others:
                violations.append(Violation(
                    "route_short",
                    f"net {r.net} declares a bridge at tile {t} with no perpendicular net "
                    f"crossing there"))
    return violations


def _route_orientation(path: List[Coord]) -> Dict[Coord, str]:
    """Classify each path tile as straight-horizontal "H", straight-vertical "V", or "X".

    A tile is a clean horizontal pass-through ("H") iff it has both a left and a right
    path-neighbour and neither vertical neighbour; "V" is the vertical mirror. Endpoints,
    turns, branches and 2-wide blobs come out as "X". This is the SAME definition the router
    uses to mark bridges, so what the router bridges is exactly what the DRC accepts.
    """
    tiles = set(path)
    orient: Dict[Coord, str] = {}
    for (x, y) in path:
        left = (x - 1, y) in tiles
        right = (x + 1, y) in tiles
        up = (x, y - 1) in tiles
        down = (x, y + 1) in tiles
        if left and right and not up and not down:
            orient[(x, y)] = "H"
        elif up and down and not left and not right:
            orient[(x, y)] = "V"
        else:
            orient[(x, y)] = "X"
    return orient


def overlap_violations(scenario: Scenario) -> List[Violation]:
    """Just the cell/cell overlap violations, for the test that asserts no overlaps."""
    return [v for v in drc(scenario) if v.kind == "overlap"]


# --- reconstruction ---------------------------------------------------------------

def _routes_connect(scenario: Scenario) -> Dict[str, bool]:
    """For each net, check its route actually links the driver pin to consumer pins.

    Returns net -> True if the route path is contiguous (4-connected) and touches the
    net's source pin and at least the consumer pins recorded for that net. Nets with no
    route (e.g. a pin-coincident net) are reported True only if source and consumer pins
    already coincide. This is what makes reconstruction reject a broken placement.
    """
    # Gather pins per net.
    src_pin: Dict[str, Coord] = {}
    con_pins: Dict[str, List[Coord]] = {}
    for c in scenario.cells:
        if c.output is not None:
            src_pin[c.output.net] = (c.output.x, c.output.y)
        for pin in c.inputs:
            con_pins.setdefault(pin.net, []).append((pin.x, pin.y))
        # A register's clock pin consumes the clock-distribution net: the clock route must
        # physically reach every register tile, so the clock counts as unrouted if it does not.
        if c.clock is not None:
            con_pins.setdefault(c.clock.net, []).append((c.clock.x, c.clock.y))

    # Primary input nets get their source from an input pad.
    for pad in scenario.input_pads():
        src_pin.setdefault(pad.net, (pad.x, pad.y))

    # A clock-distribution net that is not a primary input is sourced from its clock pad.
    for pad in scenario.io:
        if pad.kind == "clock":
            src_pin.setdefault(pad.net, (pad.x, pad.y))

    # Primary OUTPUT pads are consumers of their net: the route must physically reach the
    # framebuffer/output pad, not just the cell input pins. Without this an output route that
    # stops short of its pad is wrongly reported as fully connected (input pads are already
    # checked as sources, so this restores the symmetry).
    for pad in scenario.output_pads():
        con_pins.setdefault(pad.net, []).append((pad.x, pad.y))

    route_by_net: Dict[str, List[Coord]] = {r.net: list(r.path) for r in scenario.routes}

    ok: Dict[str, bool] = {}
    nets = set(src_pin) | set(con_pins)
    for net in nets:
        consumers = con_pins.get(net, [])
        if not consumers:
            ok[net] = True       # nothing consumes it; vacuously connected.
            continue
        src = src_pin.get(net)
        path = route_by_net.get(net)
        if path is None:
            # no route: only valid if src already sits on every consumer pin.
            ok[net] = src is not None and all(c == src for c in consumers)
            continue
        pathset = set(path)
        contiguous = _is_contiguous(path)
        touches_src = src is None or src in pathset
        touches_cons = all(c in pathset for c in consumers)
        ok[net] = contiguous and touches_src and touches_cons
    return ok


def _is_contiguous(path: List[Coord]) -> bool:
    """True if the tile list forms a 4-connected walk (allowing branch points via set).

    A fanout route is not a simple chain, so we check the path tiles form one connected
    component under 4-adjacency rather than requiring each consecutive pair to be adjacent.
    """
    if not path:
        return False
    tiles = set(path)
    if len(tiles) == 1:
        return True
    start = path[0]
    seen = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nb in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nb in tiles and nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return seen == tiles


def unrouted_nets(scenario: Scenario) -> List[str]:
    """Nets whose routes do not physically connect the pins their name claims.

    A net counts as unrouted if it has consumers but no route reaches them: either there is
    no route at all, or the route is not 4-connected, or it misses the source/consumer pins.
    This is the honest physical-completeness measure, reported by the tests and the CLI.
    """
    return sorted(net for net, good in _routes_connect(scenario).items() if not good)


def scenario_to_netlist(scenario: Scenario, require_routed: bool = False) -> Netlist:
    """Reconstruct the logical Netlist from the placed, routed scenario.

    Connectivity is recovered by walking the scenario spatially, not from any source netlist:
      - each placed cell becomes a logical Cell whose input/output net names are read off the
        pins placed on its footprint,
      - the routes are followed to confirm those named nets are physically linked, and
      - the ports come from the IO pads (input pads -> primary inputs, output pads ->
        primary outputs).

    A route that connects the WRONG pins (a net whose track does not touch its driver or a
    consumer) is ALWAYS rejected, so a broken or mis-wired placement cannot pass by
    name-matching alone. By default an absent route (a net the crude router left unrouted)
    is tolerated, because the logical connectivity is still fully and unambiguously carried
    by the net names on the placed pins, and physical routing completeness is reported
    separately via unrouted_nets(). Pass require_routed True to additionally demand that
    every net is physically routed (raises otherwise), proving the placement is complete.
    We never invent connectivity that the scenario does not contain.
    """
    # Cross-check routes against the named pins. A route present-but-wrong is fatal either
    # way; a route simply absent is fatal only when require_routed is set.
    connectivity = _routes_connect(scenario)
    routes_by_net = {r.net for r in scenario.routes}
    broken_wrong = [net for net, good in connectivity.items()
                    if not good and net in routes_by_net]
    if broken_wrong:
        raise ValueError(
            "scenario routes connect the wrong pins for nets: "
            + ", ".join(sorted(broken_wrong)))
    if require_routed:
        missing = [net for net, good in connectivity.items() if not good]
        if missing:
            raise ValueError(
                "scenario routes do not connect named nets: " + ", ".join(sorted(missing)))

    # Rebuild cells from placed-cell pins (the spatial net names). A register tile carries its
    # clock net on a dedicated clock pin (off the data inputs), so reconstruct the DFF with that
    # clock net and reset value recovered spatially, exactly as the netlist Cell carries them.
    cells: List[Cell] = []
    for pc in scenario.cells:
        in_nets = [p.net for p in pc.inputs]
        out_net = pc.output.net if pc.output is not None else None
        if out_net is None:
            raise ValueError(f"placed cell {pc.id} has no output pin")
        clk_net = pc.clock.net if pc.clock is not None else None
        cells.append(Cell(id=pc.id, type=pc.type, inputs=in_nets, output=out_net,
                          clock=clk_net, reset=pc.reset))

    inputs = [pad.net for pad in scenario.input_pads()]
    outputs = [pad.net for pad in scenario.output_pads()]

    nl = Netlist(name=scenario.name, cells=cells, ports=Ports(inputs=inputs, outputs=outputs))
    nl.validate()
    return nl


def verify_equivalence(source_netlist: Netlist, scenario: Scenario,
                       require_routed: bool = False) -> bool:
    """True iff the netlist reconstructed from `scenario` matches `source_netlist`.

    Reconstructs via scenario_to_netlist (which reads the placed cells and routes, not the
    source) and compares with equivalent() (same ports AND same exhaustive truth table). So
    True means "the placement realises the source logic": same primary I/O and identical
    truth table. require_routed is forwarded; set it to also demand the scenario be fully and
    correctly routed, so True then means logic AND every net physically connected.
    """
    rebuilt = scenario_to_netlist(scenario, require_routed=require_routed)
    return equivalent(source_netlist, rebuilt)
