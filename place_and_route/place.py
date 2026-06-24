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
CELL_W x CELL_H is the REAL computing-NOR stamp footprint, frozen from the verified
block-signal NOR (scenarios/norgate_gs, parameterised in scenarios/computecell_gs).
A cell laid at origin (cell.x, cell.y) builds, in tile-x order from the origin:

    cell.x      west depot (the reader spawns here)
    cell.x+1    first track tile (BX)
    cell.x+7    reader signal (SIGX = BX+6), eastbound-permissive (front = SIGX-1)
    cell.x+8 .. input taps, one per input (a present train on a tap = that input bit 1)
    SIGX+n+2    terminating signal (keeps the input block a through block)
    +2          east depot (the reader rests here, x = EASTX, iff it passed = NOR)

The lane runs on row cell.y+1; the feeder depots that park input trains sit on row
cell.y, just north. So the footprint is CELL_W = 14 wide (origin .. east depot for the
2-input case) and CELL_H = 3 tall (feeder row, lane row, plus one margin row). The pin
offsets below put each input pin ON its tap tile and the output pin on the reader-output
tile, so the placement the router/emitter sees is physically the same tiles the
GameScript stamps. This is the "swap in the real footprint + pin offsets" the module
header promised: nothing else in this file changes.

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

Registers (sequential designs)
------------------------------
A DFF cell is a clocked REGISTER TILE: a master-slave NOR latch, so its footprint
(REG_W x REG_H) is bigger than a combinational NOR. It has the usual data pin(s) D on the
west edge and a Q output on the east edge, PLUS a dedicated CLOCK pin on the west edge (on
its own row, off the data pins, so the clock-distribution net never shorts onto data). The
clock net is carried on Cell.clock (not in Cell.inputs), exactly mirroring the netlist, and
the router fans it from one source out to every register's clock pin (the clock spine).

A register is a TIMING BOUNDARY for the level assignment: a cell reading a register's Q does
not chain its column through the register (Q is held state, a level-0 source), which is what
makes a SEQUENTIAL netlist with feedback through a register (a counter, a toggle flip-flop)
placeable instead of looking like a combinational loop. The exact in-tile track geometry of
the register is the open research problem (TODO(human), STUCK.md); REG_W/REG_H are an honest
footprint reservation, the same way the combinational NOR footprint was reserved before its
geometry was solved in game. Placement and routing only need the extent and the pin tiles.

stdlib only. Imports the shared netlist + scenario contracts, does not modify them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from netlist import Netlist, Cell
from scenario import PlacedCell, Pin


# REAL computing-NOR stamp footprint (the verified block-signal NOR, see module docstring
# and scenarios/computecell_gs). 14 wide: origin (west depot) .. east depot for the
# 2-input case. 3 tall: feeder-depot row (cell.y), lane row (cell.y+1), one margin row.
# This is the BASELINE for the verified 1-2 input gates (NOT, NOR2). Lowering at scale (the CPU
# and the raycaster cones) produces WIDER NORs, up to ~10 inputs, whose input pins stack down the
# west edge (see _input_pin_offsets), so _cell_height GROWS the footprint to contain every pin;
# CELL_W/CELL_H stay the small-gate baseline (the in-game-proven stamp) and the column stride.
CELL_W = 14
CELL_H = 3

# Footprint offsets that pin the stamp geometry. The lane is one row below the origin so
# the feeder depots can sit on the origin row; the first tap is 8 tiles east of the origin
# (origin=west depot, +1 = BX, +7 = reader signal SIGX, +8 = first tap), matching Geom() in
# scenarios/computecell_gs/main.nut.
LANE_DY = 1          # lane row = cell.y + LANE_DY (feeder depots on cell.y)
FIRST_TAP_DX = 8     # first input tap at cell.x + FIRST_TAP_DX

# REGISTER (DFF) tile footprint. A clocked register is a master-slave pair of cross-coupled
# NOR latches (see netlist.NetlistBuilder.dff_nor), so its physical tile is BIGGER than a
# single combinational NOR: two gated latches plus the clock-gating inverter and the
# clock-distribution tap. We do not yet have the verified track geometry for that tile in
# OpenTTD (the single combinational NOR is the only gate proven in game, see STUCK.md #1), so
# REG_W/REG_H are a HONEST RESERVATION: a footprint large enough to hold the master-slave latch
# the lowering implies, with three distinct west-edge pins (D data, CLOCK, and a clear margin
# row) and a Q output on the east edge. The exact in-tile track layout of the register is
# TODO(human) and tracked in STUCK.md; placement and routing only need the footprint extent and
# the pin tiles, both of which are pinned here, so the toolchain closes around the reservation
# the same way it closed around the combinational NOR before that geometry was solved.
REG_W = 16           # wider than CELL_W (14): master + slave latch span plus the clock tap
REG_H = 4            # taller than CELL_H (3): D row, CLOCK row, Q lane, margin row
REG_CLOCK_DY = 2     # clock pin on the west edge, one row below the D data pin

# Kept for backward compatibility with _cell_height's old margin maths (unused by the real
# fixed-height footprint, but referenced below).
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
    primary inputs (or constants, which have no inputs) sit at level 0.

    Registers (DFF cells) are TIMING BOUNDARIES, not combinational links. A register output Q
    is held state, available at the START of every clock cycle just like a primary input, so a
    cell that READS a register's Q does NOT chain its level through the register: Q is treated
    as a level-0 source. This is what makes a SEQUENTIAL netlist placeable: a feedback loop that
    is broken by a register (e.g. a toggle flip-flop q = DFF(NOT q, clk), or any counter that
    feeds its own next-state back through a register) is acyclic ONCE the register edge is cut,
    so it gets sensible columns instead of raising "combinational loop". A purely COMBINATIONAL
    loop (no register on the cycle) still raises, exactly as before, since that is a real design
    error the M4 substrate cannot build. A register's OWN level is computed from its data input D
    so the register tile sits in a column to the right of the logic that feeds it.
    """
    drivers = netlist.driver_of()
    primary = set(netlist.ports.inputs)
    # Nets driven by a register output: these are timing boundaries, level-0 sources for any
    # consumer, so the recursion never crosses a register edge (and feedback through a register
    # does not look like a combinational loop).
    register_outputs = {c.output for c in netlist.cells if c.is_sequential()}
    level: Dict[str, int] = {}

    def cell_level(cell: Cell, stack: set) -> int:
        if cell.id in level:
            return level[cell.id]
        if cell.id in stack:
            raise ValueError(f"combinational loop through cell {cell.id}")
        stack.add(cell.id)
        lvl = 0
        for src in cell.inputs:
            if src in primary or src in register_outputs:
                # primary input or a register output: a level-0 timing-boundary source.
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

    The input pins land on distinct WEST-edge rows LANE_DY .. LANE_DY+n-1 (see
    _input_pin_offsets), so the footprint must be tall enough to CONTAIN every pin: a feeder
    row above the lane, the n pin rows, and the routing/DRC must see the pins inside this
    cell's own footprint. The last input pin sits at row LANE_DY + n - 1, so the footprint
    spans rows 0 .. LANE_DY + n - 1, i.e. height LANE_DY + n.

    For the verified 1-2 input gates (NOT, NOR2) this is exactly CELL_H == 3 (LANE_DY + 2 == 3),
    so the proven in-game stamp geometry is unchanged; the height only GROWS for the wider NORs
    that lowering produces at scale (the CPU / raycaster cones reach 8-10 inputs). Growing the
    footprint to hold every pin is what keeps a wide-fan-in cell from spilling its input pins
    onto open ground below its 3-tall stamp, which is the dense-design DRC short the shared
    channel router was wrongly blamed for: with the pins inside the footprint, no foreign route
    or stacked cell can land on them, and no two cells' pins collide. We never let the footprint
    shrink below CELL_H, so the small gates are byte-for-byte identical to before.
    """
    if n_inputs <= 0:
        return CELL_H
    return max(CELL_H, LANE_DY + n_inputs)


def _cell_width(n_inputs: int) -> int:
    """Footprint width for a cell with n_inputs inputs.

    The east depot sits at SIG2X + 2 = (BX+6) + n + 2 + 2 = origin + 11 + n. So a 1-input
    NOT is 13 wide and a 2-input NOR2 is 14 wide. We return the per-cell width; CELL_W (14)
    is the 2-input baseline used for the column stride so cells in a column never overlap.
    """
    n = max(1, n_inputs)
    return 12 + n


def _input_pin_offsets(n: int, h: int) -> List[tuple]:
    """Tile offsets (dx, dy) for n input pins: the cell's WEST-edge lane tiles.

    The physical input taps run east along the lane row (cell.y + LANE_DY) starting
    FIRST_TAP_DX east of the origin (the GameScript derives them from cell.x; see Geom() in
    scenarios/computecell_gs). A routed net delivering this cell's input bit cannot land in
    the cell interior without the channel router's stub cutting the cell, so the ROUTING pin
    is the WEST EDGE of the lane: a net drops its carrier train on the west edge and the lane
    carries it east into the tap block (the taps and the west approach share one signal block,
    so a train anywhere in that block reads as that input present). One pin per row down the
    short west edge so two input nets never share the entry tile. For the verified 1-2 input
    gates this is rows LANE_DY and LANE_DY+0/1; n stays small (NOT, NOR2).
    """
    if n <= 0:
        return []
    if n == 1:
        return [(0, LANE_DY)]
    # Two inputs: stack the two west-edge entry tiles on adjacent lane-side rows so each input
    # net has its own distinct entry tile (no short), both feeding the lane that runs east.
    return [(0, LANE_DY + i) for i in range(n)]


def _output_pin_offset(h: int, n: int = 2) -> tuple:
    """Tile offset (dx, dy) for the single output pin: the reader-output tile (east depot).

    The reader rests in the east depot (x = EASTX = origin + 11 + n) iff the gate output is
    1, so that tile is where a downstream cell reads this cell's output bit. It sits on the
    lane row, on the opposite (east) end from the input taps, so it never collides with one.
    """
    return (11 + max(1, n), LANE_DY)


# --- register (DFF) tile footprint -------------------------------------------------

def _register_input_pin_offsets(n: int) -> List[tuple]:
    """West-edge data (D) pin offsets for a register tile, one row per data input.

    A DFF has exactly one data input D, but we size generally: the data pins sit on the top
    west-edge rows (row LANE_DY upward), kept clear of the clock pin's row (REG_CLOCK_DY). The
    register's D enters here exactly as a combinational cell's input does, on its own tile.
    """
    if n <= 0:
        return []
    return [(0, LANE_DY + i) for i in range(n)]


def _register_clock_pin_offset() -> tuple:
    """West-edge CLOCK pin offset for a register tile.

    The clock arrives on its OWN west-edge tile, below the data pin(s), so the clock-distribution
    net never shares a tile with the register's data net (that would short the clock onto the
    data). The clock-distribution trunk drops a riser onto this tile for every register, which is
    the clock spine reaching every clock pin.
    """
    return (0, REG_CLOCK_DY)


def _register_output_pin_offset() -> tuple:
    """East-edge Q output pin offset for a register tile.

    Q (the held register value) leaves on the east edge, lane row, opposite the west-edge data
    and clock pins, so it never collides with them. Downstream cells read this cell's Q here.
    """
    return (REG_W - 1, LANE_DY)


def _channel_demand(netlist: Netlist, levels: Dict[str, int]) -> int:
    """Max number of nets that must cross any single column boundary.

    Signal flows strictly left to right (a cell's level is always greater than its driver's),
    so each net occupies the column boundaries between its driver's column and its furthest
    consumer's column. The busiest boundary sets the minimum channel width: a column gap
    narrower than this cannot physically route all the crossing nets. Primary inputs are
    treated as driven from the left margin (level -1).
    """
    primary = set(netlist.ports.inputs)
    # net -> driver column. A register output is held state available from the left, so like a
    # primary input it is sourced at level -1 (not at the register's own column): a consumer of
    # Q may sit in ANY column, even left of the register, so its crossing span must start from
    # the left margin.
    register_outputs = {c.output for c in netlist.cells if c.is_sequential()}
    src_col: Dict[str, int] = {}
    for c in netlist.cells:
        src_col[c.output] = -1 if c.is_sequential() else levels[c.id]
    for n in primary:
        src_col[n] = -1
    # The clock-distribution net is sourced from the left margin too (the clock origin pad).
    clocks = netlist.clocks()
    for clk in clocks:
        src_col.setdefault(clk, -1)
    # net -> furthest consumer column. A register's clock pin consumes the clock net at the
    # register's column, so the clock net spans the left margin out to the rightmost register.
    far_col: Dict[str, int] = {}
    for c in netlist.cells:
        for src in c.inputs:
            lvl = levels[c.id]
            if src not in far_col or lvl > far_col[src]:
                far_col[src] = lvl
        if c.clock is not None:
            lvl = levels[c.id]
            if c.clock not in far_col or lvl > far_col[c.clock]:
                far_col[c.clock] = lvl
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
    # Column stride must clear the WIDEST footprint a column can hold. Registers (REG_W) are
    # wider than a combinational NOR (CELL_W), so a column with a register needs the bigger
    # stride or the next column would overlap it. (The channel router re-spaces columns exactly
    # to per-column width afterwards; this keeps the pre-routing placement legal too.)
    widest = REG_W if netlist.is_sequential() else CELL_W
    col_stride = widest + col_gap
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
            n_in = len(c.inputs)
            cell_row[c.id] = row
            if c.is_sequential():
                # Register tile: bigger footprint, a clock pin on the west edge in addition to
                # the data pin(s), and a Q output on the east edge. The clock pin carries the
                # clock-distribution net (c.clock), kept on a distinct row from the data pins.
                ch, cw = REG_H, REG_W
                in_pins = []
                for (dx, dy), net in zip(_register_input_pin_offsets(n_in), c.inputs):
                    in_pins.append(Pin(net=net, x=cx + dx, y=cy + dy))
                cdx, cdy = _register_clock_pin_offset()
                clk_pin = Pin(net=c.clock, x=cx + cdx, y=cy + cdy)
                odx, ody = _register_output_pin_offset()
                out_pin = Pin(net=c.output, x=cx + odx, y=cy + ody)
                pc = PlacedCell(
                    id=c.id, type=c.type, x=cx, y=cy, w=cw, h=ch,
                    inputs=in_pins, output=out_pin, clock=clk_pin, reset=c.reset)
            else:
                ch = _cell_height(n_in)
                cw = _cell_width(n_in)
                in_pins = []
                for (dx, dy), net in zip(_input_pin_offsets(n_in, ch), c.inputs):
                    in_pins.append(Pin(net=net, x=cx + dx, y=cy + dy))
                odx, ody = _output_pin_offset(ch, n_in)
                out_pin = Pin(net=c.output, x=cx + odx, y=cy + ody)
                pc = PlacedCell(
                    id=c.id, type=c.type, x=cx, y=cy, w=cw, h=ch,
                    inputs=in_pins, output=out_pin)
            placed.append(pc)
            by_id[c.id] = pc
            max_x = max(max_x, cx + cw)
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
