"""Lee / BFS maze router for the openttdoom M3 backend, with congestion negotiation.

Given a Placement (from place.py) and the source Netlist, connect every net from its
driver output pin to each consumer input pin with a tile path that avoids cell footprint
interiors and (in the end) other nets' tracks. This is the "track laying" pass: on the
real substrate each Route becomes a chain of OpenTTD rail tiles carrying one signal.

Algorithm
---------
A single greedy Lee pass is very order sensitive: an early net carves a lane a later net
needs, and you strand nets that are individually routable. To actually complete routing
on a congested grid we use negotiated congestion (a cut-down Pathfinder, the algorithm
FPGA routers use):

  1. Route every net with a cost-aware flood (Dijkstra), allowing tiles to be temporarily
     shared. The per-tile cost includes a congestion penalty that is cheap when a tile is
     used by at most one net and expensive when several nets pile onto it.
  2. After each iteration, raise a persistent "history" penalty on every over-used tile.
  3. Repeat. Nets on contested tiles get pushed onto cheaper detours, and after a few
     iterations the shared tiles clear out.

We stop when no tile is shared by two nets (a legal routing) or a small iteration cap is
hit. A final legalisation pass routes nets one at a time as hard obstacles to guarantee
the committed routes never short two signals together; it tries a couple of deterministic
net orders and keeps the one that lands the most nets. Any net that still cannot find a
path is recorded as unrouted. We never fake a path: an unroutable net shows up in
RouteResult.unrouted with its endpoints and the reason.

This is a deliberately crude M3 router. It produces legal, tile-disjoint routing with zero
shorts, but it does NOT always reach 100 percent routed on congested designs (the busy
fanout nets in a multi-bit adder can box each other out). That is acceptable per the brief
("crude routing is fine"), and the gap is reported honestly, never hidden. The logical
connectivity is independent of routing completeness: it is carried by the net names on the
placed pins, so check.scenario_to_netlist can still rebuild and verify the logic even when
a few nets are left unrouted. A smarter rip-up-and-reroute or channel router is the natural
next step and is noted in STUCK.

Obstacles that are always hard (never shareable):
  - every cell footprint tile EXCEPT the pins of the current net (a route must reach its
    own pins, which sit on footprint boundaries),
  - escape tiles reserved for other nets' pins (keeps every pin reachable).

stdlib only.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from netlist import Netlist
from scenario import Route
from place import Placement

Coord = Tuple[int, int]


@dataclass
class UnroutedNet:
    net: str
    source: Coord
    target: Coord
    reason: str


@dataclass
class RouteResult:
    routes: List[Route] = field(default_factory=list)
    unrouted: List[UnroutedNet] = field(default_factory=list)

    def coverage(self) -> Tuple[int, int]:
        """(#nets fully routed, #nets total) for reporting."""
        total = len(self.routes) + len({u.net for u in self.unrouted})
        return len(self.routes), total


def _neighbors(t: Coord, w: int, h: int):
    x, y = t
    if x > 0:
        yield (x - 1, y)
    if x < w - 1:
        yield (x + 1, y)
    if y > 0:
        yield (x, y - 1)
    if y < h - 1:
        yield (x, y + 1)


@dataclass
class _RouteCtx:
    """Static routing context derived from the placement, shared across retry passes."""
    primary: Set[str]
    consumers: Dict[str, List[Coord]]
    sources: Dict[str, Coord]
    cell_tiles: Set[Coord]
    pins_of_net: Dict[str, Set[Coord]]
    escape_owner: Dict[Coord, str]
    pad_owner: Dict[Coord, str]      # IO pad tile -> the net that owns it
    map_w: int
    map_h: int


def _build_ctx(netlist: Netlist, placement: Placement,
               map_w: int, map_h: int,
               input_pads: Dict[str, Coord] | None = None,
               output_pads: Dict[str, Coord] | None = None) -> _RouteCtx:
    """Build the routing context.

    input_pads maps a primary-input net -> its pad tile; that pad becomes the net's source
    (so the route physically reaches the pad, not just the consumer pins). output_pads maps
    a primary-output net -> its pad tile; that pad is added as an extra consumer of the net
    so the route runs out to the framebuffer pixel. Both default to empty for routing that
    ignores IO (used by internal tests), but emit.py always supplies them.
    """
    input_pads = input_pads or {}
    output_pads = output_pads or {}
    primary = set(netlist.ports.inputs)
    consumers: Dict[str, List[Coord]] = {}
    sources: Dict[str, Coord] = {}
    cell_tiles: Set[Coord] = set()
    pins_of_net: Dict[str, Set[Coord]] = {}
    for pc in placement.cells:
        for t in pc.occupied():
            cell_tiles.add(t)
        if pc.output is not None:
            sources[pc.output.net] = (pc.output.x, pc.output.y)
            pins_of_net.setdefault(pc.output.net, set()).add(
                (pc.output.x, pc.output.y))
        for pin in pc.inputs:
            consumers.setdefault(pin.net, []).append((pin.x, pin.y))
            pins_of_net.setdefault(pin.net, set()).add((pin.x, pin.y))

    # IO pad tiles. A pad belongs to exactly one net; foreign routes must not run over it
    # (that would short the framebuffer pixel / input pad to another signal). pad_owner maps
    # each pad tile -> its net, and is added to the hard obstacles of every other net below.
    pad_owner: Dict[Coord, str] = {}
    # Primary-input pads are the true source of their net.
    for net, pad in input_pads.items():
        sources[net] = pad
        pins_of_net.setdefault(net, set()).add(pad)
        pad_owner[pad] = net
    # Primary-output pads are an extra consumer of their net (route runs out to them).
    for net, pad in output_pads.items():
        consumers.setdefault(net, []).append(pad)
        pins_of_net.setdefault(net, set()).add(pad)
        pad_owner[pad] = net

    # Escape tiles: a pin sits on a footprint edge, so its only way out is the one (or few)
    # non-footprint tiles next to it. Reserve every pin's escape tiles for the pin's own
    # net so no foreign route may claim them and strand the pin. escape_owner maps the
    # reserved tile -> the net allowed to use it. Output pads sit on the right map edge, so
    # reserve their inward neighbour too (the only way a route reaches the pad).
    escape_owner: Dict[Coord, str] = {}
    for pc in placement.cells:
        all_pins = list(pc.inputs)
        if pc.output is not None:
            all_pins.append(pc.output)
        for pin in all_pins:
            px, py = pin.x, pin.y
            for nb in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                if not (0 <= nb[0] < map_w and 0 <= nb[1] < map_h):
                    continue
                if nb in cell_tiles:
                    continue
                escape_owner.setdefault(nb, pin.net)
    for pad, net in pad_owner.items():
        px, py = pad
        for nb in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
            if not (0 <= nb[0] < map_w and 0 <= nb[1] < map_h):
                continue
            if nb in cell_tiles or nb in pad_owner:
                continue
            escape_owner.setdefault(nb, net)

    return _RouteCtx(primary, consumers, sources, cell_tiles, pins_of_net,
                     escape_owner, pad_owner, map_w, map_h)


def _net_endpoints(net: str, ctx: _RouteCtx):
    """Return (start_tiles, goal_list) for a net, or None if it has no source.

    A driven net starts at its driver output pin. A primary input has no driver, so it
    starts at its first consumer pin (emit.py drops the input pad on path[0]). Goals are
    the consumer pins not already in the start set.
    """
    cons = ctx.consumers.get(net, [])
    if not cons:
        return None
    if net in ctx.sources:
        start = {ctx.sources[net]}
    elif net in ctx.primary:
        start = {cons[0]}
    else:
        return None
    goals = sorted({c for c in cons if c not in start})
    return start, goals


def _dijkstra(starts: Set[Coord], goals: Set[Coord], hard: Set[Coord],
              cost_of, ctx: _RouteCtx) -> List[Coord] | None:
    """Least-cost flood from any start to the nearest goal, avoiding `hard` tiles.

    cost_of(tile) -> float is the cost of stepping onto `tile` (its base step cost plus a
    congestion penalty). start/goal tiles are always enterable even if listed in `hard`.
    Returns the tile path (inclusive of reached start and goal) or None if unreachable.
    """
    if not starts or not goals:
        return None
    immediate = starts & goals
    if immediate:
        return [sorted(immediate)[0]]

    w, h = ctx.map_w, ctx.map_h
    counter = itertools.count()
    dist: Dict[Coord, float] = {s: 0.0 for s in starts}
    prev: Dict[Coord, Coord] = {}
    pq: list = []
    for s in sorted(starts):
        heapq.heappush(pq, (0.0, next(counter), s))
    while pq:
        d, _, cur = heapq.heappop(pq)
        if d > dist.get(cur, float("inf")):
            continue
        if cur in goals and cur not in starts:
            path = [cur]
            while path[-1] not in starts:
                path.append(prev[path[-1]])
            path.reverse()
            return path
        for nb in _neighbors(cur, w, h):
            if nb in hard and nb not in goals and nb not in starts:
                continue
            nd = d + cost_of(nb)
            if nd < dist.get(nb, float("inf")):
                dist[nb] = nd
                prev[nb] = cur
                heapq.heappush(pq, (nd, next(counter), nb))
    return None


def _route_net_costed(net: str, ctx: _RouteCtx, hard: Set[Coord],
                      cost_of) -> List[Coord] | None:
    """Route one net (all fanout legs) with the cost flood. Returns the tile path or None.

    Fanout is handled Steiner-style: after the first leg, tiles already on this net's path
    are valid start points and cost nothing to reuse, so later legs branch off the trunk.
    """
    ep = _net_endpoints(net, ctx)
    if ep is None:
        return None
    start, goals = ep
    own_pins = ctx.pins_of_net.get(net, set())

    path_tiles: Set[Coord] = set(start)
    ordered: List[Coord] = list(sorted(start))

    if not goals:
        return ordered

    def cost(tile: Coord) -> float:
        if tile in path_tiles:      # reusing this net's own trunk is free
            return 0.0
        return cost_of(tile)

    for goal in goals:
        if goal in path_tiles:
            continue
        # this net's own pins are never hard for itself
        leg = _dijkstra(set(path_tiles), {goal}, hard - own_pins, cost, ctx)
        if leg is None:
            return None
        for t in leg:
            if t not in path_tiles:
                ordered.append(t)
            path_tiles.add(t)
    return ordered


def route_nets(netlist: Netlist, placement: Placement,
               map_w: int, map_h: int,
               input_pads: Dict[str, Coord] | None = None,
               output_pads: Dict[str, Coord] | None = None) -> RouteResult:
    """Route every net of `netlist` over the placed grid via negotiated congestion.

    A single greedy maze pass is order sensitive and strands nets that are individually
    routable. We use negotiated congestion (a cut-down Pathfinder): route every net with a
    cost-aware Dijkstra flood that lets tiles be temporarily shared, then raise a persistent
    "history" penalty on every over-used tile and repeat, so contested nets are pushed onto
    cheaper detours. After it settles, a single greedy legalisation pass (easiest nets first,
    each committed as a hard obstacle for the rest) lands a tile-disjoint routing. The
    placement sizes channels to the busiest boundary, so there is room for this to converge.

    input_pads / output_pads tie each primary IO net to its pad tile so the routed track
    physically reaches the pad (see _build_ctx). Returns a RouteResult whose committed
    routes never share a tile (no shorted signals); any net that still cannot be legalised
    is recorded in `.unrouted`, never faked.
    """
    ctx = _build_ctx(netlist, placement, map_w, map_h, input_pads, output_pads)
    nets = [n for n in netlist.nets()
            if (n in ctx.consumers or n in ctx.sources) and ctx.consumers.get(n)]

    # Hard obstacles common to every net: cell footprints + foreign escape reservations +
    # foreign IO pad tiles, minus the net's own pins (which it must be allowed to reach).
    foreign_escapes_for: Dict[str, Set[Coord]] = {}
    foreign_pads_for: Dict[str, Set[Coord]] = {}
    for net in nets:
        foreign_escapes_for[net] = {t for t, owner in ctx.escape_owner.items()
                                    if owner != net}
        foreign_pads_for[net] = {t for t, owner in ctx.pad_owner.items()
                                 if owner != net}

    def hard_for(net: str) -> Set[Coord]:
        own = ctx.pins_of_net.get(net, set())
        return (ctx.cell_tiles | foreign_escapes_for[net] | foreign_pads_for[net]) - own

    # Negotiated-congestion state.
    history: Dict[Coord, float] = {}     # persistent penalty, grows on over-use
    present: Dict[Coord, int] = {}       # how many nets currently sit on a tile

    BASE = 1.0
    HIST_GROW = 1.5
    PRESENT_FAC = 4.0
    MAX_ITERS = 8

    def cost_of(tile: Coord) -> float:
        return BASE + history.get(tile, 0.0) + PRESENT_FAC * present.get(tile, 0)

    def fanout(n): return len(ctx.consumers.get(n, []))

    def span(n):
        ys = [y for (_, y) in ctx.consumers.get(n, [])]
        if n in ctx.sources:
            ys.append(ctx.sources[n][1])
        return (max(ys) - min(ys)) if ys else 0

    idx = {n: i for i, n in enumerate(nets)}
    # Easiest first: short, low-fanout nets have little routing freedom, so they grab their
    # direct paths before high-fanout nets (which can weave around) sprawl across the grid.
    order = sorted(nets, key=lambda n: (fanout(n), span(n), idx[n]))

    for _iteration in range(MAX_ITERS):
        present = {}
        for net in order:
            p = _route_net_costed(net, ctx, hard_for(net), cost_of)
            if p is None:
                continue
            own = ctx.pins_of_net.get(net, set())
            for t in p:
                if t not in own:
                    present[t] = present.get(t, 0) + 1
        overused = [t for t, c in present.items() if c > 1]
        if not overused:
            break
        for t in overused:
            history[t] = history.get(t, 0.0) + HIST_GROW * present[t]

    # Legalisation: commit nets one at a time as hard obstacles so the final routes are
    # tile-disjoint (no two signals share a tile). The history penalty from negotiation has
    # already spread the nets out. Greedy legalisation is order sensitive (hardest-first
    # gives the long fanout nets room but blobs over short hops; easiest-first does the
    # reverse), so we run a few deterministic orders and keep the one that routes the most
    # nets. Whatever still cannot be placed is honestly recorded as unrouted, never faked.
    # A full rip-up-and-reroute engine would push coverage higher but is out of scope for
    # crude M3 routing; the brief explicitly allows crude routing with recorded unrouted nets.
    def legal_cost(tile: Coord) -> float:
        return BASE + history.get(tile, 0.0)

    def legalise(net_order: List[str]) -> RouteResult:
        res = RouteResult()
        used: Set[Coord] = set()
        for net in net_order:
            own = ctx.pins_of_net.get(net, set())
            hard = (hard_for(net) | used) - own
            p = _route_net_costed(net, ctx, hard, legal_cost)
            if p is None:
                ep = _net_endpoints(net, ctx)
                if ep is None:
                    res.unrouted.append(
                        UnroutedNet(net, (-1, -1),
                                    ctx.consumers.get(net, [(-1, -1)])[0],
                                    "no source/driver"))
                else:
                    start, goals = ep
                    src0 = sorted(start)[0]
                    tgt = goals[0] if goals else src0
                    res.unrouted.append(UnroutedNet(net, src0, tgt, "no path (blocked)"))
                continue
            for t in p:
                if t not in own:
                    used.add(t)
            res.routes.append(Route(net=net, path=p))
        return res

    easiest_first = sorted(nets, key=lambda n: (fanout(n), span(n), idx[n]))
    hardest_first = sorted(nets, key=lambda n: (-fanout(n), -span(n), idx[n]))
    best: RouteResult | None = None
    for net_order in (easiest_first, hardest_first):
        res = legalise(net_order)
        if best is None or len(res.routes) > len(best.routes):
            best = res
        if not res.unrouted:
            break
    assert best is not None
    return best
