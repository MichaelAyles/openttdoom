"""Deterministic grid placement for the openttdoom M3 backend.

Takes a NOR-lowered Netlist and assigns every cell a tile footprint and position on
the OpenTTD map. Placement is deterministic so the same netlist always lands on the
same tiles, which keeps the downstream router and the equivalence check reproducible.

Strategy
--------
Cells are placed in columns by topological logic level (level 0 = cells whose inputs
are all primary inputs), and in rows by their order within that level. Primary inputs
are pads down the left edge, so signal flows left to right across the map. This is the
simplest layout that guarantees a driver is always in a column left of its consumers,
which gives the maze router an easy, mostly monotone job.

Footprint
---------
CELL_W x CELL_H is a placeholder stamp for the real M2 gate geometry. The verified M2
NOR construction has its own physical size (track, signals, a train loop); until that
geometry is frozen we reserve a 3xH tile block per cell, which is large enough to drop
pins on distinct boundary tiles and leave the interior for the gate guts. When M2 lands,
update CELL_W / CELL_H / the pin offsets to match the real stamp and nothing else here
needs to change.

NOR is unbounded fan-in (max_in == -1), so a wide NOR can have more inputs than the
baseline CELL_H has left-edge tiles. We therefore size each cell's height to its own
fan-in (see _cell_height): the footprint grows tall enough that every input pin gets a
distinct boundary tile. Two different nets never share a tile, which the substrate would
otherwise read as a short. The per-cell height is carried on PlacedCell.h, so route.py
and emit.py size the footprint correctly without any extra change.

Pin convention (on the footprint boundary):
  - inputs enter on the LEFT edge (x == cell.x), one per tile down the column of left
    tiles, so each input net occupies its own distinct tile.
  - the single output leaves on the RIGHT edge, middle tile (x == cell.x + w - 1).

stdlib only. Imports the shared netlist + scenario contracts, does not modify them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from netlist import Netlist, Cell
from scenario import PlacedCell, Pin


# Placeholder footprint for one buildable cell (NOR / CONST0 / CONST1).
# 3x3 is the baseline: 3 wide so input pins and the output pin sit on opposite edges, and
# at least 3 tall so the gate guts have an interior. A cell with more than CELL_H inputs
# is made taller per _cell_height so every input pin still gets its own tile.
# This is a PLACEHOLDER for the real M2 gate stamp geometry, see module docstring.
CELL_W = 3
CELL_H = 3

# Extra tile rows kept above/below the input-pin stack on a tall cell, so the gate guts
# have a margin and the output pin (placed at the vertical middle) does not collide with an
# input pin. A wide NOR's footprint height is n_inputs + 2 * PIN_MARGIN, floored at CELL_H.
PIN_MARGIN = 1

# Baseline spacing between cell columns and rows, in tiles. The gap is routing channel: the
# maze router threads nets through these empty lanes between footprints. COL_GAP here is a
# floor; place_cells() widens the actual column stride to fit the busiest channel of the
# design (see _channel_demand), because a column gap narrower than the number of nets that
# must cross it physically cannot route them. ROW_GAP gives vertical detour lanes between
# stacked cells. Generous on purpose: M3 routing is crude and we would rather spend tiles
# than strand nets. Tighten once a smarter router lands.
COL_GAP = 6
ROW_GAP = 6

# Left margin reserved for input pads and the first routing channel. Wide enough that a
# primary input fanning out down the whole left edge has clear vertical lanes to every row.
LEFT_MARGIN = 8
TOP_MARGIN = 2

# Extra tracks added on top of the measured channel demand, so the router always has slack
# to detour and the legaliser does not have to pack channels perfectly.
CHANNEL_SLACK = 4


@dataclass
class Placement:
    """Result of placing a netlist: positioned cells plus the grid metrics used.

    `cells` is the list of PlacedCell ready for routing. `by_id` indexes them. The grid
    metrics are kept so route.py and emit.py can size the map and find the output column.
    """
    cells: List[PlacedCell]
    by_id: Dict[str, PlacedCell]
    levels: Dict[str, int]          # cell id -> logic level (column index)
    width_tiles: int                # rightmost tile used + 1
    height_tiles: int               # bottommost tile used + 1


def logic_levels(netlist: Netlist) -> Dict[str, int]:
    """Assign each cell a topological level. Level = longest path from a primary input.

    A cell's level is 1 + max(level of cells driving its inputs); cells fed only by
    primary inputs (or constants, which have no inputs) sit at level 0. Raises on a
    combinational loop, matching netlist.simulate's contract (M4 substrate is acyclic).
    """
    drivers = netlist.driver_of()
    primary = set(netlist.ports.inputs)
    level: Dict[str, int] = {}

    def cell_level(cell: Cell, stack: set) -> int:
        if cell.id in level:
            return level[cell.id]
        if cell.id in stack:
            raise ValueError(f"combinational loop through cell {cell.id}")
        stack.add(cell.id)
        lvl = 0
        for src in cell.inputs:
            if src in primary:
                continue
            drv = drivers.get(src)
            if drv is None:
                # undriven net; validate() would have caught it, treat as level 0 source.
                continue
            lvl = max(lvl, cell_level(drv, stack) + 1)
        stack.discard(cell.id)
        level[cell.id] = lvl
        return lvl

    for c in netlist.cells:
        cell_level(c, set())
    return level


def _cell_height(n_inputs: int) -> int:
    """Footprint height for a cell with n_inputs inputs.

    Tall enough that every input pin gets its own distinct left-edge tile: at least CELL_H,
    and n_inputs + 2 * PIN_MARGIN for a wide cell (NOR is unbounded fan-in, max_in == -1).
    The margin keeps a row of guts above and below the pin stack and stops the middle-row
    output pin from landing on an input row in the small-fan-in case.
    """
    return max(CELL_H, n_inputs + 2 * PIN_MARGIN)


def _input_pin_offsets(n: int, h: int) -> List[tuple]:
    """Tile offsets (dx, dy) on the left edge for n input pins, top to bottom.

    One pin per tile down the left column, so every input net occupies a DISTINCT tile and
    no two nets ever share a tile (which the substrate would read as a short). `h` is the
    cell's footprint height from _cell_height, which is sized so n pins always fit.
    """
    if n <= 0:
        return []
    if n == 1:
        return [(0, h // 2)]
    # Centre the pin stack vertically within the footprint, one pin per row.
    top = (h - n) // 2
    return [(0, top + i) for i in range(n)]


def _output_pin_offset(h: int) -> tuple:
    """Tile offset (dx, dy) for the single output pin on the right edge, middle row.

    The output sits on the opposite (right) edge from the inputs, so it can never share a
    tile with an input pin regardless of height.
    """
    return (CELL_W - 1, h // 2)


def _channel_demand(netlist: Netlist, levels: Dict[str, int]) -> int:
    """Max number of nets that must cross any single column boundary.

    Signal flows strictly left to right (a cell's level is always greater than its driver's),
    so each net occupies the column boundaries between its driver's column and its furthest
    consumer's column. The busiest boundary sets the minimum channel width: a column gap
    narrower than this cannot physically route all the crossing nets. Primary inputs are
    treated as driven from the left margin (level -1).
    """
    primary = set(netlist.ports.inputs)
    # net -> driver column
    src_col: Dict[str, int] = {}
    for c in netlist.cells:
        src_col[c.output] = levels[c.id]
    for n in primary:
        src_col[n] = -1
    # net -> furthest consumer column
    far_col: Dict[str, int] = {}
    for c in netlist.cells:
        for src in c.inputs:
            lvl = levels[c.id]
            if src not in far_col or lvl > far_col[src]:
                far_col[src] = lvl
    counts: Dict[int, int] = {}
    for net, sc in src_col.items():
        fc = far_col.get(net)
        if fc is None:
            continue
        for boundary in range(sc, fc):
            counts[boundary] = counts.get(boundary, 0) + 1
    return max(counts.values()) if counts else 0


def place_cells(netlist: Netlist) -> Placement:
    """Place every cell of `netlist` on a deterministic column/row grid.

    Columns are logic levels (left to right). Within a column, cells are ordered by the
    barycenter of their driver rows: a cell sits at roughly the average row of the cells
    feeding it, in the column immediately to its left. This clusters connected logic so a
    net's driver and consumers end up near the same row, which keeps wires short and the
    routing channels uncongested. The pass is deterministic (stable tie-breaks on netlist
    order), so the same netlist always lands identically.

    Returns a Placement; the caller (route.py / emit.py) reads .cells and the grid metrics.
    """
    netlist.validate()
    levels = logic_levels(netlist)
    drivers = netlist.driver_of()

    # Group cell ids by level, preserving netlist order within a level as the base order.
    by_level: Dict[int, List[Cell]] = {}
    for c in netlist.cells:
        by_level.setdefault(levels[c.id], []).append(c)

    # Size the inter-column channel to the busiest boundary so every crossing net has a
    # vertical track, plus slack. This is what makes routing reliably complete: a fixed
    # narrow gap cannot carry more nets than it has tiles.
    demand = _channel_demand(netlist, levels)
    col_gap = max(COL_GAP, demand + CHANNEL_SLACK)
    col_stride = CELL_W + col_gap
    # Cells can have different heights (a wide NOR is taller, see _cell_height), so rows are
    # packed by a running y cursor per column rather than a fixed row stride: each cell starts
    # ROW_GAP below the bottom of the cell above it. Footprint heights vary by fan-in.
    # The left margin carries the primary inputs fanning into the first columns, so size it
    # like a channel too: at least every primary input gets a vertical lane, plus slack.
    left_margin = max(LEFT_MARGIN, len(netlist.ports.inputs) + CHANNEL_SLACK)

    placed: List[PlacedCell] = []
    by_id: Dict[str, PlacedCell] = {}
    # row index assigned to each cell, used to compute the barycenter of later columns.
    cell_row: Dict[str, int] = {}
    netlist_index = {c.id: i for i, c in enumerate(netlist.cells)}
    max_x = 0
    max_y = 0

    for lvl in sorted(by_level):
        col_cells = by_level[lvl]
        cx = left_margin + lvl * col_stride

        # Barycenter: average driver row. Cells whose inputs are all primary inputs (no
        # placed driver) keep a neutral key so they fall back to netlist order, spread
        # down the column. This is a single ordering pass, not iterative, which is plenty
        # for the shallow combinational netlists M3 targets.
        def barycenter(c: Cell) -> float:
            rows = []
            for src in c.inputs:
                drv = drivers.get(src)
                if drv is not None and drv.id in cell_row:
                    rows.append(cell_row[drv.id])
            if not rows:
                return float(netlist_index[c.id])  # stable fallback for level-0 cells
            return sum(rows) / len(rows)

        ordered = sorted(col_cells, key=lambda c: (barycenter(c), netlist_index[c.id]))

        cy = TOP_MARGIN
        for row, c in enumerate(ordered):
            ch = _cell_height(len(c.inputs))
            cell_row[c.id] = row
            in_pins = []
            for (dx, dy), net in zip(_input_pin_offsets(len(c.inputs), ch), c.inputs):
                in_pins.append(Pin(net=net, x=cx + dx, y=cy + dy))
            odx, ody = _output_pin_offset(ch)
            out_pin = Pin(net=c.output, x=cx + odx, y=cy + ody)
            pc = PlacedCell(
                id=c.id, type=c.type, x=cx, y=cy, w=CELL_W, h=ch,
                inputs=in_pins, output=out_pin)
            placed.append(pc)
            by_id[c.id] = pc
            max_x = max(max_x, cx + CELL_W)
            max_y = max(max_y, cy + ch)
            # Advance the cursor past this cell's footprint plus the routing row gap, so the
            # next cell in this column never overlaps a tall cell above it.
            cy += ch + ROW_GAP

    return Placement(
        cells=placed,
        by_id=by_id,
        levels=levels,
        width_tiles=max_x,
        height_tiles=max_y,
    )
