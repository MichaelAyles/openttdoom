"""Constructive, guaranteed-complete channel router for the openttdoom M3 backend.

This replaces the maze router (route.py). The maze router topped out near 77/101 nets on
the 4-bit adder NOT because it was a weak heuristic, but because it forbids crossings: every
committed route is tile-disjoint, and a 4-bit adder netlist is not planar, so some wire
crossings are topologically unavoidable. OpenTTD's real way to cross two tracks is a BRIDGE,
one track passing over a perpendicular track. So the principled fix is to allow perpendicular
bridge crossings, which makes complete routing achievable and is faithful to how OpenTTD
logic layouts actually cross signals.

The scheme is constructive (no search, no backtracking), so it is deterministic and always
completes. It is designed so there is never a parallel same-direction overlap, and every
crossing between two different nets is perpendicular (a legal bridge):

  WIDEN. First the placement is x-expanded so every inter-column channel (and the left/right
  margins) is wide enough to hold one distinct vertical track per riser that lands in it.
  Spending tiles here is cheap (OpenTTD maps are large) and is what guarantees every pin gets
  its own clear riser column without ever crossing a cell. Cell rows/heights are untouched.

  TRUNK ROWS. Each net gets a UNIQUE horizontal trunk row (a distinct y in a reserved band
  below the logic). Two nets' horizontal runs therefore never share a tile.

  RISERS. Each pin of a net connects to that net's trunk row with a VERTICAL riser on its own
  UNIQUE vertical track column, sitting in the channel beside the pin (left of an input pin,
  right of an output pin). No two vertical segments ever share a tile.

  STUBS. A pin escapes its cell with a short HORIZONTAL stub on the pin's own row, from the
  pin to its riser column in the adjacent channel. Within one channel the left cell's output
  pins take the LEFT tracks and the right cell's input pins take the RIGHT tracks, so two
  stubs sharing a row come from opposite sides and occupy disjoint x-ranges. They never
  overlap and never cross a cell (the channel between them is clear).

  TRUNK JOIN. Below the logic each riser drops onto its net's unique trunk row, a single
  horizontal run joining all of that net's risers (fanout to all sinks off the one trunk row).

  CROSSINGS. A horizontal trunk of net A crossing a vertical riser of net B is a legal
  perpendicular bridge: the trunk is carried OVER the riser, and the trunk net records the
  tile in its Route.bridges. Two segments of the SAME orientation never share a tile (that
  would be a real short), which the construction guarantees because trunks have unique rows
  and risers have unique columns.

The result is a fully routed scenario with zero genuine shorts: every net reaches every pin,
and every shared tile is a clean perpendicular bridge crossing recorded honestly in bridges.

Sequential designs (the clock-distribution net). A register tile (a placed DFF) carries its
clock on a dedicated clock pin, which the router treats as a consumer of the clock net. The
clock net is then routed exactly like any data net: one source (a clock source pad, or the
clk primary-input pad, or a cell-driven clock's driver) fans out to every register's clock pin
via the net's unique trunk row. That trunk row is the CLOCK SPINE, a single horizontal run the
width of the design with a riser dropping onto each register's clock pin, so the clock reaches
every register tile. It crosses other nets only as legal perpendicular bridges, so no
clock-specific routing rule is needed (honest simplification: a single spine, not a buffered
H-tree, which suits the train-loop clock model in scenarios/gate_model.py).

stdlib only.
"""

from __future__ import annotations

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
    width_tiles: int = 0      # rightmost tile used + 1 (router may extend past the logic)
    height_tiles: int = 0     # bottommost tile used + 1
    # IO pad tiles after the router's x-widening, so emit.py's IOPad list and framebuffer
    # match the routed tiles. net -> (x, y). Empty for the internal (no-IO) test path.
    input_pads: Dict[str, Coord] = field(default_factory=dict)
    output_pads: Dict[str, Coord] = field(default_factory=dict)
    # Clock-distribution source pads after widening (the clock origin tiles), net -> (x, y), for
    # clock nets that are not themselves primary inputs. Empty when the clock is a primary input.
    clock_pads: Dict[str, Coord] = field(default_factory=dict)

    def coverage(self) -> Tuple[int, int]:
        """(#nets fully routed, #nets total) for reporting."""
        total = len(self.routes) + len({u.net for u in self.unrouted})
        return len(self.routes), total


# Gap between the trunk band and the bottom of the logic, and slack tracks per channel.
BAND_GAP = 2
CHANNEL_SLACK = 2


@dataclass
class _Pin:
    net: str
    x: int
    y: int
    side: str           # "right" = escapes toward +x, "left" = escapes toward -x
    role: str           # "driver" / "consumer" / "pad_in" / "pad_out"


def _vline(x: int, y0: int, y1: int) -> List[Coord]:
    if y1 >= y0:
        return [(x, y) for y in range(y0, y1 + 1)]
    return [(x, y) for y in range(y0, y1 - 1, -1)]


def _hline(y: int, x0: int, x1: int) -> List[Coord]:
    if x1 >= x0:
        return [(x, y) for x in range(x0, x1 + 1)]
    return [(x, y) for x in range(x0, x1 - 1, -1)]


def _widen_placement(placement: Placement, left_pad_demand: int) -> Dict[int, int]:
    """Spread cell columns apart so every channel holds one track per riser, return x-remap.

    Each cell column (cells sharing an origin x) needs, in the gap to its LEFT, one clear
    column per input pin of that column's cells (those pins escape left) and, in the gap to
    its RIGHT, one clear column per output pin (those escape right). The left margin before the
    first column must also hold one track per primary-input pad (left_pad_demand). We lay the
    columns out left to right with gaps sized to that demand plus slack, mutate every cell's x
    and pin x in place, and return the old-x -> new-x map for the column origins so the caller
    can remap IO pads consistently. Cell heights, rows and the relative pin offsets within a
    cell are untouched, so the placement stays legal.
    """
    cells = placement.cells
    if not cells:
        return {}
    col_w = {}                     # column origin x -> footprint width (per-column max)
    col_in = {}                    # column origin x -> total west-edge pins of its cells
    col_out = {}                   # column origin x -> total output pins of its cells
    for c in cells:
        col_w[c.x] = max(col_w.get(c.x, 0), c.w)
        # A register's CLOCK pin escapes left too (the clock-distribution riser lands beside
        # it), so it counts toward the left-channel demand exactly like a data input pin.
        west_pins = len(c.inputs) + (1 if c.clock is not None else 0)
        col_in[c.x] = col_in.get(c.x, 0) + west_pins
        col_out[c.x] = col_out.get(c.x, 0) + (1 if c.output is not None else 0)
    old_cols = sorted(col_w)

    # Risers are spaced 2 columns apart (never adjacent, see _assign_riser_columns), so each
    # riser needs 2 channel columns. Size the left margin and every gap for 2x the riser
    # demand that lands in it, plus slack. The left margin holds the first column's input-pin
    # risers AND every input pad's riser (both land there, so the demands ADD).
    SP = 2
    remap: Dict[int, int] = {}
    cursor = SP * (left_pad_demand + col_in[old_cols[0]]) + CHANNEL_SLACK + 2
    prev_right_demand = 0
    for j, ox in enumerate(old_cols):
        if j > 0:
            # Gap before this column: previous column's output risers + this column's input
            # risers, each times the 2-column spacing, plus slack.
            gap = SP * (prev_right_demand + col_in[ox]) + CHANNEL_SLACK + 2
            cursor += gap
        remap[ox] = cursor
        cursor += col_w[ox]            # advance past this column's footprint
        prev_right_demand = col_out[ox]

    # Apply the remap to every cell and its pins (shift x only; y unchanged).
    for c in cells:
        nx = remap[c.x]
        dx = nx - c.x
        c.x = nx
        for p in c.inputs:
            p.x += dx
        if c.output is not None:
            c.output.x += dx
        if c.clock is not None:
            c.clock.x += dx

    placement.width_tiles = cursor
    return remap


def _collect_pins(placement: Placement,
                  input_pads: Dict[str, Coord],
                  output_pads: Dict[str, Coord],
                  clock_pads: Dict[str, Coord] | None = None) -> List[_Pin]:
    """Gather every pin (cell pins + IO pads + clock source pads) with its escape side."""
    pins: List[_Pin] = []
    for pc in placement.cells:
        for ip in pc.inputs:
            pins.append(_Pin(ip.net, ip.x, ip.y, side="left", role="consumer"))
        # A register's clock pin is a consumer of the clock-distribution net: it escapes left
        # like a data input, and the clock trunk fans a riser onto it (the clock reaching every
        # register tile is exactly this set of consumers).
        if pc.clock is not None:
            pins.append(_Pin(pc.clock.net, pc.clock.x, pc.clock.y,
                             side="left", role="clk_sink"))
        if pc.output is not None:
            pins.append(_Pin(pc.output.net, pc.output.x, pc.output.y,
                             side="right", role="driver"))
    for net, (px, py) in input_pads.items():
        pins.append(_Pin(net, px, py, side="right", role="pad_in"))
    for net, (px, py) in output_pads.items():
        pins.append(_Pin(net, px, py, side="left", role="pad_out"))
    # The clock SOURCE pad drives the clock-distribution net (the clock origin tile on the left
    # edge). It is the single driver of the clock net; every register's clk_sink is fed from it.
    for net, (px, py) in (clock_pads or {}).items():
        pins.append(_Pin(net, px, py, side="right", role="pad_clk"))
    return pins


def _assign_riser_columns(pins: List[_Pin], cell_tiles: Set[Coord],
                          blocked_cols: Set[int],
                          far_x: int) -> Tuple[Dict[int, int], int]:
    """Give every pin a UNIQUE vertical riser column clear of all cells, top to bottom.

    A riser runs from its pin's row down to the trunk band, so its column must be empty at
    every row (not in blocked_cols, the set of cell-occupied columns) and the stub from the
    pin to it must cross no cell: we scan outward from the pin on its own row and STOP at the
    first cell tile. After _widen_placement there is always a free clear column on the pin's
    escape side before any cell, so the scan succeeds. The left/right track split (output pins
    take left tracks, input pins take right tracks of a channel) keeps stubs that share a row
    disjoint. A far-right band guarantees a fallback column for pads against the map edge.
    Returns (pin_index -> riser_x, rightmost_x_used + 1).
    """
    claimed: Set[int] = set()
    riser_of: Dict[int, int] = {}
    used_max = far_x
    far_next = [far_x]

    def col_free(x: int) -> bool:
        return x >= 0 and x not in claimed and x not in blocked_cols

    def scan(px: int, py: int, step: int) -> int | None:
        x = px + step
        while x >= 0:
            if (x, py) in cell_tiles:
                return None
            if col_free(x):
                return x
            x += step
            if step > 0 and x > far_next[0] + len(pins) + 4:
                return None
        return None

    def take(i: int, col: int) -> None:
        # Claim the column AND its immediate neighbours, so no two risers ever sit on adjacent
        # columns. That keeps every riser an ISOLATED vertical line: a foreign trunk crossing
        # it sees a clean single-tile vertical pass-through (a legal perpendicular bridge), not
        # a 2-wide strip that would defeat the crossing test.
        claimed.add(col)
        claimed.add(col - 1)
        claimed.add(col + 1)
        riser_of[i] = col

    def assign(i: int, p: _Pin) -> None:
        order = (1, -1) if p.side == "right" else (-1, 1)
        for step in order:
            col = scan(p.x, p.y, step)
            if col is not None:
                take(i, col)
                return
        # Fall back to a private far-right column, reached straight across only if the pin row
        # is clear of cells out to the band (so the stub cuts nothing).
        clear = all((x, p.y) not in cell_tiles for x in range(p.x + 1, far_next[0]))
        if clear:
            col = far_next[0]
            far_next[0] += 2          # +2 keeps far-band risers non-adjacent too
            take(i, col)
            return
        # Should not happen after widening; if it does, take the nearest free column to the
        # right. It surfaces honestly as a route_cuts_cell DRC violation, never a faked path.
        x = p.x + 1
        while not col_free(x):
            x += 1
        take(i, x)

    # Right-escaping pins first (claim left side of their right channel), then left-escaping.
    for i, p in enumerate(pins):
        if p.side == "right":
            assign(i, p)
            used_max = max(used_max, riser_of[i] + 1)
    for i, p in enumerate(pins):
        if p.side == "left":
            assign(i, p)
            used_max = max(used_max, riser_of[i] + 1)
    return riser_of, max(used_max, far_next[0])


def route_nets(netlist: Netlist, placement: Placement,
               map_w: int, map_h: int,
               input_pads: Dict[str, Coord] | None = None,
               output_pads: Dict[str, Coord] | None = None,
               clock_pads: Dict[str, Coord] | None = None) -> RouteResult:
    """Route every net constructively into trunks + risers with perpendicular bridges.

    The placement is x-widened in place first (cells shift right; rows unchanged), so emit.py
    must read placement.cells AFTER this call. input_pads / output_pads are remapped to the
    widened coordinate system and the updated tiles are written back into the dicts the caller
    passed, so emit.py's IOPad list stays consistent with the routed tiles.

    clock_pads maps each clock-distribution net to its CLOCK SOURCE tile on the left edge. The
    clock net is just another routed net: a single source pad (the clock origin) fanning out to
    every register's clock pin via the net's unique trunk row. That trunk row IS the clock spine
    (a single horizontal run carrying the clock the width of the design), and each register's
    clock riser drops off it onto the register's clock pin, so the clock physically reaches every
    register tile. It crosses other nets only as legal perpendicular bridges, exactly like data
    nets, so no special clock-tree machinery is needed beyond naming the source.

    Returns a RouteResult whose routes carry the tile path and the bridge tiles (where THIS net
    is carried OVER a perpendicular crossing). Deterministic and complete: every net with a
    source and at least one sink is routed. width_tiles / height_tiles report the used extent
    so emit.py can size the map.

    Disjointness invariants (verified by the DRC):
      - trunk rows unique per net   -> no horizontal trunk shares a tile,
      - riser columns unique per pin -> no two risers share a tile,
      - in-channel stubs from opposite sides never overlap and never cut a cell,
      - the ONLY tiles shared by two nets are perpendicular bridge crossings.
    """
    input_pads = dict(input_pads or {})
    output_pads = dict(output_pads or {})
    clock_pads = dict(clock_pads or {})

    # 1. Widen the placement so every channel has a track per riser. Input pads AND clock source
    #    pads sit on the left edge (x = 0) and need left-margin tracks too, hence left_pad_demand.
    remap = _widen_placement(placement,
                             left_pad_demand=len(input_pads) + len(clock_pads))

    # 2. Remap IO pads into the widened coordinates. Input pads and clock source pads stay at
    #    x = 0 (left edge); output pads move to just past the widened logic.
    new_right_x = placement.width_tiles + 1
    for net in list(input_pads):
        x, y = input_pads[net]
        input_pads[net] = (0, y)
    for net in list(clock_pads):
        x, y = clock_pads[net]
        clock_pads[net] = (0, y)
    for j, net in enumerate(list(output_pads)):
        x, y = output_pads[net]
        output_pads[net] = (new_right_x, y)

    all_pins = _collect_pins(placement, input_pads, output_pads, clock_pads)
    pins_by_net: Dict[str, List[int]] = {}
    for i, p in enumerate(all_pins):
        pins_by_net.setdefault(p.net, []).append(i)

    sources: Dict[str, int] = {}
    for net, idxs in pins_by_net.items():
        for i in idxs:
            if all_pins[i].role in ("driver", "pad_in", "pad_clk"):
                sources[net] = i
                break

    cell_tiles: Set[Coord] = set()
    blocked_cols: Set[int] = set()
    for pc in placement.cells:
        for t in pc.occupied():
            cell_tiles.add(t)
        for x in range(pc.x, pc.x + pc.w):
            blocked_cols.add(x)

    max_x = placement.width_tiles
    max_y = placement.height_tiles
    for p in all_pins:
        max_x = max(max_x, p.x + 1)
        max_y = max(max_y, p.y + 1)

    far_x = max_x + 2
    riser_of, riser_max_x = _assign_riser_columns(all_pins, cell_tiles, blocked_cols, far_x)

    nets_ordered = [n for n in netlist.nets() if n in pins_by_net]
    trunk_y0 = max_y + BAND_GAP
    trunk_row: Dict[str, int] = {net: trunk_y0 + i for i, net in enumerate(nets_ordered)}

    result = RouteResult()
    used_w = max(riser_max_x, max_x)
    used_h = max_y

    for net in nets_ordered:
        idxs = pins_by_net[net]
        consumers = [i for i in idxs
                     if all_pins[i].role in ("consumer", "pad_out", "clk_sink")]
        src = sources.get(net)
        if src is None:
            tgt = ((all_pins[consumers[0]].x, all_pins[consumers[0]].y)
                   if consumers else (-1, -1))
            result.unrouted.append(UnroutedNet(net, (-1, -1), tgt, "no source/driver"))
            continue
        if not consumers:
            continue

        ty = trunk_row[net]
        path_tiles: List[Coord] = []
        path_set: Set[Coord] = set()

        def add(tiles: List[Coord]):
            for t in tiles:
                if t not in path_set:
                    path_set.add(t)
                    path_tiles.append(t)

        riser_xs: List[int] = []
        for i in idxs:
            p = all_pins[i]
            rx = riser_of[i]
            add(_hline(p.y, p.x, rx))      # stub: pin -> riser column on the pin's row
            add(_vline(rx, p.y, ty))       # riser: down to the trunk row
            riser_xs.append(rx)
            used_h = max(used_h, p.y + 1)
            used_w = max(used_w, rx + 1)

        add(_hline(ty, min(riser_xs), max(riser_xs)))   # trunk joins all risers
        used_h = max(used_h, ty + 1)
        result.routes.append(Route(net=net, path=path_tiles, bridges=[]))

    _assign_bridges(result)
    result.width_tiles = used_w
    result.height_tiles = used_h
    # Hand the remapped IO + clock pad tiles back so the caller's IOPad list matches the routes.
    result.input_pads = input_pads
    result.output_pads = output_pads
    result.clock_pads = clock_pads
    return result


def _segment_orientation(path: List[Coord]) -> Dict[Coord, str]:
    """Classify each tile as straight-horizontal "H", straight-vertical "V", or other "X".

    A tile is "H" iff it has both a left and a right path-neighbour and neither vertical
    neighbour; "V" is the mirror. The DRC uses the same definition, so a router-marked bridge
    is exactly what the DRC accepts as a clean perpendicular crossing.
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


def _assign_bridges(result: RouteResult) -> None:
    """Mark, for every perpendicular crossing of two routes, which net bridges over.

    A tile shared by two nets is a clean perpendicular crossing iff it is a straight horizontal
    pass-through in one net's path and a straight vertical pass-through in the other's. By
    construction that is the only way two nets share a tile (unique trunk rows + unique riser
    columns rule out same-orientation overlaps). The HORIZONTAL (trunk) net is carried over, so
    it records the tile in its bridges list. Deterministic and symmetric: exactly one net
    bridges each crossing.
    """
    orient: Dict[str, Dict[Coord, str]] = {}
    owners: Dict[Coord, List[str]] = {}
    route_by_net: Dict[str, Route] = {}
    for r in result.routes:
        orient[r.net] = _segment_orientation(r.path)
        route_by_net[r.net] = r
        for t in r.path:
            owners.setdefault(t, []).append(r.net)

    for t, nets in owners.items():
        if len(nets) != 2:
            continue
        a, b = nets
        oa = orient[a].get(t, "X")
        ob = orient[b].get(t, "X")
        if oa == "H" and ob == "V":
            route_by_net[a].bridges.append(t)
        elif ob == "H" and oa == "V":
            route_by_net[b].bridges.append(t)

    for r in result.routes:
        r.bridges.sort()
