"""The hardwired raycaster FSM: render_reference_hw as real synchronous hardware.

This is deliverable B of the project: the gorgeous-within-1-bit raycaster rebuilt as a
dedicated, clocked STATE MACHINE (NOT a CPU, NOT a CHIP-8), so it can run on the train
substrate. It reproduces golden/raycaster.py::render_reference_hw for the 64x32 signal panel
("lo" res) BIT FOR BIT, the same equality contract test_raycaster.py pins for the CHIP-8 ROM.

Why an FSM and not the CPU. hdl/cpu.py is a general accumulator machine that fetches and
executes a program. This module is the opposite: every wire is dedicated to one job, the DDA
ray march and the per-pixel paint. There is no instruction stream, no program counter over a
ROM of opcodes; the control is a small hand-built FSM and the "program" is hardwired landscape
(the trig / reciprocal / shade / Bayer / texture LUTs, exactly the tables render_reference_hw
indexes). That is the right shape for the substrate: a LUT is free hardwired track, a register
bit is an expensive train, so the design spends almost nothing on state and everything on
combinational table lookups.

The oracle it matches (golden/raycaster.py::render_reference_hw, res="lo")
------------------------------------------------------------------------
Per column c (0..31, each drawn 2px wide -> 64px):
  - angle = (heading + COL_ANGLE[c]) mod 32.
  - DDA march from the player position: each micro-step adds/subtracts the per-angle delta
    magnitude (with the sign LUT) to x and y, then tests MAP[(y>>4)*16 + (x>>4)]; the first
    solid cell ends the cast at hit-step `dist` (1..STEPS), and the sub-cell wall fraction
    `frac` (0..15) is read from the low nibble of the crossed axis.
  - slice height = RECIP[dist], top = (32 - h)//2, bot = top + h (always bot > top: RECIP
    bottoms out at 3, so every column has a wall slice and the 1px seams always apply).
  - wall shade = HW_STEP_SHADE[dist], plus the HW_WALL_TEX[frac] bias when texture is on.
  - a column is a DEPTH EDGE if |dist - dist(neighbour)| >= 4 for either neighbour.
Per pixel (y, x):
  - ceiling (y < top): lit iff CEIL_SHADE[ri] > 0 and BAYER[y&3][x&3] < CEIL_SHADE[ri],
    ri = clamp(half-1-y).
  - floor (y >= bot): lit iff FLOOR_SHADE[ri] > 0 and BAYER[y&3][x&3] < FLOOR_SHADE[ri],
    ri = clamp(y-half).
  - wall (top <= y < bot): the slice's 1px black seams (y==top or y==bot-1) and the whole
    slice on a depth edge are forced DARK; otherwise lit iff BAYER[y&3][x&3] < shade.
This per-pixel rule is a pure WRITE-ONCE function: each framebuffer bit is computed once and
written once, in scan order, no read-modify-write. (render_reference_hw paints then clears the
seams as a second pass; the closed form folds the clear into the lit test, which is proven
identical to the oracle for every heading and both texture settings in test_raycaster_fsm.py.)

Three views, mirroring hdl/cpu.py:

  1. RaycasterFsm: a behavioural Amaranth module (m.d.sync registers for the small control /
     datapath state, an Array of framebuffer bits for the 64x32 panel). It instantiates ONE
     hdl/alu.py Alu8 for the DDA add / subtract / compare. Simulated with amaranth.sim; the
     headline test asserts its rendered framebuffer equals render_reference_hw bit for bit over
     a heading sweep.
  2. fsm_reference(): a plain Python model of the SAME cycle-accurate dataflow (the sliding
     three-column distance window, the write-once paint), the ground truth the behavioural
     module is checked against, and itself checked against render_reference_hw.
  3. build_raycaster_datapath_netlist(): the per-column + per-pixel COMBINATIONAL datapath as a
     gate-level Netlist (the DDA step, the LUT ROMs, the paint decision), built from
     NetlistBuilder so it lowers to {NOR, CONST0, CONST1}. This is the buildable cone the FSM
     wraps in registers; the report counts its NOR cells. The full registered machine's register
     budget is reported by fsm_register_bits().

State budget (the scarce resource on the substrate; counted by fsm_register_bits()):
    heading   5   the view angle (0..31), the only input
    cast_col  6   the column being cast (one ahead of the painted column)
    px, py    8+8 the marching ray position
    step      6   DDA step counter
    d_prev    6   left-neighbour hit step (for the depth-edge test)
    d_cur     6   hit step of the column being painted
    d_next    6   right-neighbour hit step
    f_cur     4   painted column's wall fraction
    f_next    4   pipelined next-column wall fraction
    hit_d     6   latched cast result (dist), consumed by the window slide
    hit_f     4   latched cast result (frac)
    row       6   the paint row counter 0..32
    paint_col 6   the column being painted
    tex       1   texture-enable latch
    phase     2   the control FSM state
  84 control / datapath register bits, plus the 64x32 = 2048-bit framebuffer (the output
  signal panel itself, the on-map pixels). The framebuffer is the OUTPUT, not working state.

NO em-dashes, integer only, deterministic. The float in the LUT builders is module-load
hardwired-landscape exactly as in render_reference_hw and the CHIP-8 ROM's tables.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from amaranth.hdl import Array, Cat, Const, Elaboratable, Module, Mux, Signal, signed

from netlist import Netlist, NetlistBuilder
from alu import Alu8, OP_ADD

# Pull the frozen oracle tables straight from the golden model: they are the hardwired
# landscape this FSM walks, so the FSM and the oracle index the SAME constants by construction.
import raycaster as rc


# --- panel geometry (the 64x32 signal panel, render_reference_hw res="lo") ----------

W = rc.SCREEN_W            # 64
H = rc.SCREEN_H            # 32
COLS = rc.NUM_COLS         # 32 rays
COLW = W // COLS           # 2 px per ray
HALF = H // 2              # 16
STEPS = rc.STEPS           # 48 max DDA micro-steps
DEPTH_SEAM_THRESH = 4      # matches render_reference_hw's DEPTH_SEAM_THRESH for the lo panel

# the plane shade LUTs sized to the lo panel's half height, built once exactly as the oracle
# builds them per call (integer math, deterministic).
FLOOR_SHADE = rc._build_plane_shade_lut_int(H - HALF, near=11, far=1, gamma_num=8, gamma_den=5)
CEIL_SHADE = rc._build_plane_shade_lut_int(HALF, near=4, far=0, gamma_num=11, gamma_den=5)

# the integer LUTs the oracle indexes, surfaced under local names for the hardware tables.
COL_ANGLE = list(rc.COL_ANGLE)        # per-column angle offset (mod 32)
DIRX_MAG = list(rc.DIRX_MAG)          # per-angle |dx| in 0..3
DIRY_MAG = list(rc.DIRY_MAG)          # per-angle |dy| in 0..3
SIGNX = list(rc.SIGNX)                # per-angle x sign bit
SIGNY = list(rc.SIGNY)                # per-angle y sign bit
RECIP = list(rc.RECIP)                # hit-step -> slice height (2..32)
HW_STEP_SHADE = list(rc.HW_STEP_SHADE)  # hit-step -> wall shade (2..13)
HW_WALL_TEX = list(rc.HW_WALL_TEX)    # wall fraction -> signed shade bias (-2..2)
BAYER = [row[:] for row in rc.BAYER4_HW]  # 4x4 ordered-dither threshold matrix
MAP = bytes(rc.MAP)                    # 16x16 map, 1 = wall
MAP_N = rc.MAP_N                       # 16
PLAYER_X = rc.PLAYER_X
PLAYER_Y = rc.PLAYER_Y
NUM_ANGLES = rc.NUM_ANGLES             # 32


# --- the write-once per-pixel paint, as plain integer functions ---------------------
#
# These are the exact decisions the hardware makes per pixel. They take only integers and
# return 0/1, so they double as the golden reference for the per-pixel combinational cone and
# as the body of fsm_reference below. Proven equal to render_reference_hw in the tests.

def _slice_top_bot(dist: int) -> Tuple[int, int]:
    """Slice top/bottom rows for a hit step, exactly as render_reference_hw (lo, hscale=1)."""
    line_h = RECIP[dist]
    if line_h > H:
        line_h = H
    top = (H - line_h) // 2
    if top < 0:
        top = 0
    bot = top + line_h
    if bot > H:
        bot = H
    return top, bot


def _wall_shade(dist: int, frac: int, texture: bool) -> int:
    """Wall shade for a column, with the optional texture bias, clamped 2..16."""
    shade = HW_STEP_SHADE[dist]
    if texture:
        shade = max(2, min(16, shade + HW_WALL_TEX[frac & 0x0F]))
    return shade


def _pixel(y: int, x: int, top: int, bot: int, shade: int, depth_edge: bool) -> int:
    """The final 0/1 value of pixel (y, x) in a column with the given slice / shade / edge.

    A pure write-once decision: ceiling, floor, or wall by the row, the wall seams and depth
    edge folded into the wall lit-test. This is the closed form proven identical to the
    oracle's paint-then-clear-seams two-pass in test_raycaster_fsm.py.
    """
    b = BAYER[y & 3][x & 3]
    if y < top:
        ri = HALF - 1 - y
        if ri < 0:
            ri = 0
        if ri >= len(CEIL_SHADE):
            ri = len(CEIL_SHADE) - 1
        s = CEIL_SHADE[ri]
        return 1 if (s > 0 and b < s) else 0
    if y >= bot:
        ri = y - HALF
        if ri < 0:
            ri = 0
        if ri >= len(FLOOR_SHADE):
            ri = len(FLOOR_SHADE) - 1
        s = FLOOR_SHADE[ri]
        return 1 if (s > 0 and b < s) else 0
    # wall row: seams (top, bot-1) and the whole slice on a depth edge are forced dark.
    if y == top or y == bot - 1 or depth_edge:
        return 0
    return 1 if b < shade else 0


# --- view 3: the plain Python cycle-accurate model (the FSM dataflow ground truth) --

def _cast(heading: int, c: int) -> Tuple[int, int]:
    """Cast column c at a heading via the oracle's integer DDA, returning (dist, frac)."""
    ang = (heading + COL_ANGLE[c]) % NUM_ANGLES
    return rc._cast_hw(PLAYER_X, PLAYER_Y, ang)


def fsm_reference(heading: int, texture: bool = True) -> np.ndarray:
    """The raycaster FSM's frame, computed by the SAME dataflow the hardware uses.

    Mirrors the machine exactly: a left-to-right column walk keeping a three-column distance
    window (prev / cur / next) for the depth-edge test, and a write-once per-pixel paint. This
    is the behavioural module's ground truth; it is itself asserted equal to
    render_reference_hw(res="lo") for every heading in the tests, so the chain
    oracle == fsm_reference == RaycasterFsm is closed.
    """
    disp = np.zeros((H, W), dtype=np.uint8)
    dist = [_cast(heading, c)[0] for c in range(COLS)]
    frac = [_cast(heading, c)[1] for c in range(COLS)]
    for c in range(COLS):
        dl = dist[c - 1] if c > 0 else dist[c]
        dr = dist[c + 1] if c < COLS - 1 else dist[c]
        depth_edge = abs(dist[c] - dl) >= DEPTH_SEAM_THRESH or \
            abs(dist[c] - dr) >= DEPTH_SEAM_THRESH
        top, bot = _slice_top_bot(dist[c])
        shade = _wall_shade(dist[c], frac[c], texture)
        for k in range(COLW):
            x = c * COLW + k
            for y in range(H):
                disp[y, x] = _pixel(y, x, top, bot, shade, depth_edge)
    return disp


# --- view 1: the behavioural Amaranth FSM (the clocked machine) ---------------------

# control FSM phases.
PH_CAST = 0     # marching the DDA for the current column
PH_LATCH = 1    # cast finished: latch dist_cur/frac_cur, slide the window, prep neighbours
PH_PAINT = 2    # painting the previous column's 64-wide-as-2 pixels, row by row
PH_DONE = 3     # frame complete, hold


class RaycasterFsm(Elaboratable):
    """The hardwired raycaster as a synchronous state machine.

    Renders render_reference_hw(heading, res="lo") into a 64x32 framebuffer of 1-bit output
    pads. Instantiates ONE Alu8 for the DDA arithmetic and compares; the trig / reciprocal /
    shade / Bayer / texture tables are hardwired combinational ROMs (constant Arrays). The small
    control + datapath state is m.d.sync registers (see fsm_register_bits for the budget).

    Ports:
      heading  [5]  input, the view angle 0..31 (sampled once, at start of frame).
      texture       input, 1 to enable the wall-texture LUT (matches the oracle's `texture`).
      start         input, pulse high to (re)start a frame from column 0.
      done          output, high once the whole frame is painted and stable.
      The framebuffer is exposed as `pix`, a flat Array of W*H 1-bit Signals in row-major scan
      order (pix[y*W + x]); read it after `done` rises. fb_value(ctx) packs it to a numpy frame.

    The machine walks: for each column, PH_CAST marches the DDA one micro-step per clock using
    the Alu8 (add or subtract the per-angle magnitude, then the >>4 cell index and the map
    test); on a hit (or STEPS) PH_LATCH slides the three-column distance window; PH_PAINT writes
    that column's two pixel columns, one row per clock, write-once via the _pixel decision built
    in gates; then on to the next column, and PH_DONE when column 32 is reached.
    """

    def __init__(self):
        self.heading = Signal(5)
        self.texture = Signal(init=1)
        self.start = Signal()
        self.done = Signal()
        # the framebuffer: W*H one-bit pads, row-major (pix[y*W + x]).
        self.pix = Array(Signal(name=f"pix_{y}_{x}") for y in range(H) for x in range(W))

    # -- table elaboration helpers (hardwired ROMs) --
    @staticmethod
    def _rom(m: Module, name: str, table: List[int], width: int, index: Signal) -> Signal:
        arr = Array(Const(v & ((1 << width) - 1), width) for v in table)
        out = Signal(width, name=name)
        m.d.comb += out.eq(arr[index])
        return out

    def elaborate(self, platform):
        m = Module()

        # ONE shared ALU for the DDA add / subtract / compare.
        alu = Alu8()
        m.submodules.alu = alu

        # -- small control / datapath state (m.d.sync registers) --
        # The painting needs a column's two NEIGHBOUR distances for the depth-edge test, so the
        # machine streams a three-column window: it casts column `cast_col` one step ahead and
        # paints column `cast_col - 1` from (d_prev, d_cur, d_next) = (col-2, col-1, col). The
        # fraction of the painted column rides alongside in f_cur.
        heading = Signal(5)
        cast_col = Signal(range(COLS + 2))      # column currently being cast (0..COLS)
        px = Signal(8)
        py = Signal(8)
        step = Signal(range(STEPS + 2))         # DDA micro-step counter
        d_prev = Signal(range(STEPS + 1))       # left neighbour of the painted column
        d_cur = Signal(range(STEPS + 1))        # the painted column's hit step
        d_next = Signal(range(STEPS + 1))       # right neighbour (just cast)
        f_cur = Signal(4)                       # painted column's wall fraction
        f_next = Signal(4)                      # just-cast column's wall fraction (pipelined)
        # the just-finished cast's result, latched on the hit cycle (so PH_LATCH consumes a
        # stable register, not a combinational value computed from the already-advanced step).
        hit_d = Signal(range(STEPS + 1))
        hit_f = Signal(4)
        row = Signal(range(H + 1))              # paint row 0..H
        paint_col = Signal(range(COLS + 1))     # the column being painted
        phase = Signal(2, init=PH_DONE)
        tex = Signal()

        m.d.comb += self.done.eq(phase == PH_DONE)

        # -- hardwired LUT ROMs, indexed combinationally (the trig / sign tables) --
        # angle = (heading + COL_ANGLE[cast_col]) mod 32.
        col_idx = Signal(range(COLS))
        m.d.comb += col_idx.eq(cast_col[:5])
        col_angle = self._rom(m, "col_angle", COL_ANGLE, 5, col_idx)
        angle = Signal(5)
        m.d.comb += angle.eq((heading + col_angle)[:5])      # mod 32 via 5-bit truncation
        dirx = self._rom(m, "dirx", DIRX_MAG, 2, angle)
        diry = self._rom(m, "diry", DIRY_MAG, 2, angle)
        signx = self._rom(m, "signx", SIGNX, 1, angle)
        signy = self._rom(m, "signy", SIGNY, 1, angle)

        # -- the DDA micro-step datapath, the one Alu8 carrying the x add/subtract --
        # The Alu8 is the load-bearing arithmetic unit: it adds (or subtracts, by the x sign) the
        # per-angle delta magnitude to the ray x each micro-step. OP_ADD (0x4) and OP_SUB (0x5)
        # differ only in bit 0, so the op is OP_ADD | signx. The y axis is the identical +/- of a
        # 0..3 magnitude on an 8-bit byte (the same operation), expressed inline.
        new_x = Signal(8)
        new_y = Signal(8)
        m.d.comb += [
            alu.vx.eq(px),
            alu.vy.eq(dirx),
            alu.op.eq(OP_ADD | signx),
        ]
        m.d.comb += new_x.eq(alu.result)
        y_add = (py + diry)[:8]
        y_sub = (py - diry)[:8]
        m.d.comb += new_y.eq(Mux(signy, y_sub, y_add))

        # cell index of the (new_x, new_y) position: idx = (new_y & 0xF0) | (new_x >> 4).
        cx = Signal(4)
        cy = Signal(4)
        m.d.comb += cx.eq(new_x[4:8])
        m.d.comb += cy.eq(new_y[4:8])
        map_idx = Signal(8)
        m.d.comb += map_idx.eq(Cat(cx, cy))              # cy*16 + cx
        solid = self._rom(m, "solid", [int(v) for v in MAP], 1, map_idx)

        # wall fraction at the hit, per the oracle's face pick (integer compare on the deltas).
        prev_cx = Signal(4)
        prev_cy = Signal(4)
        m.d.comb += prev_cx.eq(px[4:8])
        m.d.comb += prev_cy.eq(py[4:8])
        crossed_x = Signal()
        crossed_y = Signal()
        m.d.comb += crossed_x.eq(cx != prev_cx)
        m.d.comb += crossed_y.eq(cy != prev_cy)
        frac_pick = Signal(4)
        with m.If(crossed_x & ~crossed_y):
            m.d.comb += frac_pick.eq(new_y[0:4])         # vertical face: texture by y
        with m.Elif(crossed_y & ~crossed_x):
            m.d.comb += frac_pick.eq(new_x[0:4])         # horizontal face: texture by x
        with m.Else():
            with m.If(dirx >= diry):                     # corner: dominant ray axis
                m.d.comb += frac_pick.eq(new_y[0:4])
            with m.Else():
                m.d.comb += frac_pick.eq(new_x[0:4])

        # -- per-column paint geometry (combinational from d_cur / f_cur) --
        line_h = self._rom(m, "recip", RECIP, 6, d_cur)
        # RECIP maxes at H (32) for the lo panel, so line_h <= H and no clamp branch is needed.
        top = Signal(range(H + 1))
        bot = Signal(range(H + 1))
        m.d.comb += top.eq((H - line_h) >> 1)
        m.d.comb += bot.eq(top + line_h)
        base_shade = self._rom(m, "stepshade", HW_STEP_SHADE, 5, d_cur)
        # texture bias: signed HW_WALL_TEX[frac] added to base_shade, clamped to 2..16.
        texbias = self._rom(m, "walltex", [v & 0x1F for v in HW_WALL_TEX], 5, f_cur)
        shade_raw = Signal(signed(7))
        m.d.comb += shade_raw.eq(base_shade.as_signed() + texbias.as_signed())
        shade_tex = Signal(5)
        with m.If(shade_raw < 2):
            m.d.comb += shade_tex.eq(2)
        with m.Elif(shade_raw > 16):
            m.d.comb += shade_tex.eq(16)
        with m.Else():
            m.d.comb += shade_tex.eq(shade_raw[:5])
        shade = Signal(5)
        m.d.comb += shade.eq(Mux(tex, shade_tex, base_shade))

        # depth edge for the painted column: |d_cur - d_prev| >= 4 or |d_cur - d_next| >= 4.
        def abs_ge_thresh(a, b):
            d = Signal(signed(7))
            m.d.comb += d.eq(a.as_signed() - b.as_signed())
            ge = Signal()
            m.d.comb += ge.eq((d >= DEPTH_SEAM_THRESH) | (d <= -DEPTH_SEAM_THRESH))
            return ge
        depth_edge = Signal()
        m.d.comb += depth_edge.eq(
            abs_ge_thresh(d_cur, d_prev) | abs_ge_thresh(d_cur, d_next))

        # -- per-pixel paint decision (write-once), for the current paint row --
        # The painted column is 2px wide: x = paint_col*2 + k. Both pixels are written this cycle
        # (their x parity differs, so they hit different Bayer columns). One write each, no
        # read-modify-write: the slice seams and depth edge are folded into the wall lit-test.
        bayer_flat = [BAYER[yy][xx] for yy in range(4) for xx in range(4)]

        def paint_bit(xparity):
            # x & 3 = (2*paint_col + xparity) & 3 = {xparity, paint_col[0]}.
            bx = Signal(2)
            m.d.comb += bx.eq(Cat(Const(xparity, 1), paint_col[0]))
            by = row[0:2]
            bidx = Signal(4)
            m.d.comb += bidx.eq(Cat(bx, by))             # by*4 + bx
            bval = self._rom(m, f"bayer_{xparity}", bayer_flat, 4, bidx)

            # ceiling shade: ri = clamp(HALF-1-row, 0, len-1).
            ceil_ri = Signal(range(len(CEIL_SHADE)))
            ri_c = (HALF - 1) - row
            with m.If(ri_c < 0):
                m.d.comb += ceil_ri.eq(0)
            with m.Elif(ri_c >= len(CEIL_SHADE)):
                m.d.comb += ceil_ri.eq(len(CEIL_SHADE) - 1)
            with m.Else():
                m.d.comb += ceil_ri.eq(ri_c)
            ceil_s = self._rom(m, f"ceil_{xparity}", CEIL_SHADE, 5, ceil_ri)

            # floor shade: ri = clamp(row-HALF, 0, len-1).
            floor_ri = Signal(range(len(FLOOR_SHADE)))
            ri_f = row.as_signed() - HALF
            with m.If(ri_f < 0):
                m.d.comb += floor_ri.eq(0)
            with m.Elif(ri_f >= len(FLOOR_SHADE)):
                m.d.comb += floor_ri.eq(len(FLOOR_SHADE) - 1)
            with m.Else():
                m.d.comb += floor_ri.eq(ri_f)
            floor_s = self._rom(m, f"floor_{xparity}", FLOOR_SHADE, 5, floor_ri)

            lit = Signal()
            with m.If(row < top):
                m.d.comb += lit.eq((ceil_s > 0) & (bval < ceil_s))
            with m.Elif(row >= bot):
                m.d.comb += lit.eq((floor_s > 0) & (bval < floor_s))
            with m.Else():
                is_seam = (row == top) | (row == bot - 1)
                with m.If(is_seam | depth_edge):
                    m.d.comb += lit.eq(0)
                with m.Else():
                    m.d.comb += lit.eq(bval < shade)
            return lit

        lit0 = paint_bit(0)
        lit1 = paint_bit(1)

        # the cast result THIS cycle, combinational from the CURRENT step (pre-increment), so on
        # the hitting cycle step+1 is the hit step. Latched into hit_d/hit_f below, then consumed
        # one cycle later in PH_LATCH (after step has already advanced, hence the register).
        hit_dist = Signal(range(STEPS + 1))
        hit_frac = Signal(4)
        m.d.comb += hit_dist.eq(Mux(solid, step + 1, STEPS))
        m.d.comb += hit_frac.eq(Mux(solid, frac_pick, 0))

        def restart_cast():
            m.d.sync += [px.eq(PLAYER_X), py.eq(PLAYER_Y), step.eq(0)]

        # -- the control FSM ----------------------------------------------------------
        with m.If(self.start):
            m.d.sync += [
                heading.eq(self.heading),
                tex.eq(self.texture),
                cast_col.eq(0),
                paint_col.eq(0),
                phase.eq(PH_CAST),
            ]
            restart_cast()
        with m.Else():
            with m.Switch(phase):
                with m.Case(PH_CAST):
                    # one DDA micro-step on the column `cast_col`.
                    m.d.sync += [px.eq(new_x), py.eq(new_y), step.eq(step + 1)]
                    with m.If(solid | (step >= STEPS - 1)):
                        # cast finished: LATCH this column's (dist, frac) on the hit cycle, while
                        # step is still the pre-increment value, then advance to PH_LATCH.
                        m.d.sync += [hit_d.eq(hit_dist), hit_f.eq(hit_frac),
                                     phase.eq(PH_LATCH)]
                with m.Case(PH_LATCH):
                    # slide the three-column window from the latched hit: the column just cast is
                    # the new right neighbour; the old right neighbour becomes the column to paint.
                    with m.If(cast_col == 0):
                        # only column 0 cast so far: no paintable column yet (its left neighbour is
                        # undefined). Seed the window so column 0's neighbours are itself, then
                        # cast column 1.
                        m.d.sync += [d_prev.eq(hit_d), d_cur.eq(hit_d), d_next.eq(hit_d),
                                     f_cur.eq(hit_f), f_next.eq(hit_f),
                                     cast_col.eq(1), phase.eq(PH_CAST)]
                        restart_cast()
                    with m.Else():
                        m.d.sync += [
                            d_prev.eq(d_cur),
                            d_cur.eq(d_next),
                            d_next.eq(hit_d),
                            f_cur.eq(f_next),
                            f_next.eq(hit_f),
                            row.eq(0),
                            phase.eq(PH_PAINT),
                        ]
                with m.Case(PH_PAINT):
                    # write the two pixels of (paint_col, row).
                    x0 = paint_col * COLW
                    m.d.sync += self.pix[row * W + x0].eq(lit0)
                    m.d.sync += self.pix[row * W + x0 + 1].eq(lit1)
                    with m.If(row == H - 1):
                        with m.If(paint_col == COLS - 1):
                            m.d.sync += [paint_col.eq(paint_col + 1), phase.eq(PH_DONE)]
                        with m.Elif(cast_col == COLS - 1):
                            # all columns cast; the last paintable column's right neighbour is
                            # itself (the oracle clamps the edge neighbour). Slide so the final
                            # column paints with next == cur, then paint it.
                            m.d.sync += [d_prev.eq(d_cur), d_cur.eq(d_next),
                                         f_cur.eq(f_next), paint_col.eq(paint_col + 1),
                                         row.eq(0), phase.eq(PH_PAINT)]
                        with m.Else():
                            # advance: cast the next lookahead column, paint the next column after.
                            m.d.sync += [paint_col.eq(paint_col + 1),
                                         cast_col.eq(cast_col + 1), phase.eq(PH_CAST)]
                            restart_cast()
                    with m.Else():
                        m.d.sync += row.eq(row + 1)
                with m.Case(PH_DONE):
                    pass

        return m

    # -- readout helper for the testbench --
    def fb_value(self, ctx) -> np.ndarray:
        frame = np.zeros((H, W), dtype=np.uint8)
        for y in range(H):
            for x in range(W):
                frame[y, x] = ctx.get(self.pix[y * W + x])
        return frame


# --- view 2: the combinational datapath as a buildable NOR netlist ------------------
#
# The registered machine's combinational core is two cones: the DDA micro-step (advance + map
# test + frac pick) and the per-pixel paint decision. Both are pure integer logic, so they build
# from NetlistBuilder and lower to {NOR, CONST0, CONST1}. We build the PER-PIXEL PAINT cone here
# (the larger, table-heavy one) as the representative buildable datapath whose NOR cost the
# report counts; it is checked exhaustively against _pixel in the tests, and it is the cone the
# framebuffer writes consume each paint cycle.


def build_paint_cone_netlist() -> Netlist:
    """The per-pixel paint decision as a gate-level Netlist (one output bit `lit`).

    Inputs (all the integers the paint needs, as bit-buses, bit0 = LSB):
        y[5]      the screen row 0..31
        x[6]      the screen column 0..63
        top[6]    slice top row
        bot[6]    slice bottom row
        shade[5]  wall shade 0..16
        edge      depth-edge flag
    Output:
        lit       the final 0/1 pixel value, == _pixel(y, x, top, bot, shade, edge).

    Built purely from NetlistBuilder emitters, so it lowers to {NOR, CONST0, CONST1} via
    to_nor(). The Bayer / floor / ceiling shade tables are realised as hardwired multiplexers
    (the same ROM-as-mux pattern hdl/cpu.py uses for its program ROM), which is exactly how a
    LUT becomes free landscape on the substrate.
    """
    b = NetlistBuilder("paint")
    y = [b.declare_input(f"y{i}") for i in range(5)]
    x = [b.declare_input(f"x{i}") for i in range(6)]
    top = [b.declare_input(f"top{i}") for i in range(6)]
    bot = [b.declare_input(f"bot{i}") for i in range(6)]
    shade = [b.declare_input(f"shade{i}") for i in range(5)]
    edge = b.declare_input("edge")

    zero = b.const0()
    one = b.const1()

    def const_bits(value: int, width: int) -> List[str]:
        return [one if (value >> i) & 1 else zero for i in range(width)]

    def ripple_sub(xb: List[str], yb: List[str]):
        """xb - yb via xb + ~yb + 1. Returns (diff_bits, borrow_out_is_0_means_ge)."""
        carry = one
        sums = []
        for i in range(len(xb)):
            nyi = b.inv(yb[i])
            axb = b.xor2(xb[i], nyi)
            s_i = b.xor2(axb, carry)
            ab = b.and_([xb[i], nyi])
            cc = b.and_([carry, axb])
            carry = b.or_([ab, cc])
            sums.append(s_i)
        return sums, carry          # carry==1 means xb >= yb (no borrow)

    def ult(xb: List[str], yb: List[str]) -> str:
        """1 iff xb < yb (unsigned), equal widths."""
        _d, ge = ripple_sub(xb, yb)
        return b.inv(ge)            # NOT(xb>=yb) == xb<yb

    def uge(xb: List[str], yb: List[str]) -> str:
        _d, ge = ripple_sub(xb, yb)
        return ge

    def eq(xb: List[str], yb: List[str]) -> str:
        terms = [b.xnor2(xb[i], yb[i]) for i in range(len(xb))]
        return b.and_(terms)

    def mux2_bit(sel: str, a: str, b_: str) -> str:
        nsel = b.inv(sel)
        return b.or_([b.and_([a, nsel]), b.and_([b_, sel])])

    def mux2(sel: str, a: List[str], b_: List[str]) -> List[str]:
        return [mux2_bit(sel, a[i], b_[i]) for i in range(len(a))]

    def rom(index_bits: List[str], table: List[int], width: int) -> List[str]:
        """Hardwired ROM: a |index|-way mux over `table`, returning `width` output bits."""
        n = 1 << len(index_bits)
        onehot = []
        for v in range(n):
            lits = [index_bits[i] if (v >> i) & 1 else b.inv(index_bits[i])
                    for i in range(len(index_bits))]
            onehot.append(b.and_(lits))
        outs = []
        for bit in range(width):
            terms = []
            for v in range(n):
                tv = table[v] if v < len(table) else 0
                if (tv >> bit) & 1:
                    terms.append(onehot[v])
            outs.append(b.or_(terms) if terms else zero)
        return outs

    # bayer = BAYER[y&3][x&3], indexed by {x[0:2], y[0:2]} -> by*4 + bx.
    bayer_flat = [BAYER[yy][xx] for yy in range(4) for xx in range(4)]
    bayer = rom([x[0], x[1], y[0], y[1]], bayer_flat, 4)

    # ceiling: ri = clamp(HALF-1-y, 0, len-1); s = CEIL_SHADE[ri]; lit_c = s>0 & bayer<s.
    half_m1 = const_bits(HALF - 1, 6)
    y6 = list(y) + [zero]                              # widen y to 6 bits
    ri_c_raw, ri_c_ge = ripple_sub(half_m1, y6)        # HALF-1-y, ge==1 means HALF-1>=y
    # if HALF-1 < y, ri underflows -> clamp to 0 (handled: ge==0 -> ri 0). Else clamp high.
    ri_c_hi = uge(ri_c_raw, const_bits(len(CEIL_SHADE), 6))
    ri_c_clamped_hi = mux2(ri_c_hi, ri_c_raw, const_bits(len(CEIL_SHADE) - 1, 6))
    ri_c = mux2(b.inv(ri_c_ge), ri_c_clamped_hi, const_bits(0, 6))
    ceil_s = rom(ri_c[:4], CEIL_SHADE, 5)              # len 16 -> 4 index bits
    ceil_pos = b.inv(b.nor(ceil_s))                    # ceil_s > 0
    lit_ceil = b.and_([ceil_pos, ult(bayer + [zero], ceil_s)])

    # floor: ri = clamp(y-HALF,0,len-1); s = FLOOR_SHADE[ri]; lit_f = s>0 & bayer<s.
    ri_f_raw, ri_f_ge = ripple_sub(y6, const_bits(HALF, 6))   # y-HALF, ge==1 means y>=HALF
    ri_f_hi = uge(ri_f_raw, const_bits(len(FLOOR_SHADE), 6))
    ri_f_clamped_hi = mux2(ri_f_hi, ri_f_raw, const_bits(len(FLOOR_SHADE) - 1, 6))
    ri_f = mux2(b.inv(ri_f_ge), ri_f_clamped_hi, const_bits(0, 6))
    floor_s = rom(ri_f[:4], FLOOR_SHADE, 5)
    floor_pos = b.inv(b.nor(floor_s))
    lit_floor = b.and_([floor_pos, ult(bayer + [zero], floor_s)])

    # wall: seam (y==top or y==bot-1) or edge -> dark; else bayer < shade.
    y_is_top = eq(y6, top)
    bot_m1, _ = ripple_sub(bot, const_bits(1, 6))
    y_is_botm1 = eq(y6, bot_m1)
    seam = b.or_([y_is_top, y_is_botm1, edge])
    bayer5 = bayer + [zero]                            # widen to 5 for compare with shade
    lit_wall = b.and_([b.inv(seam), ult(bayer5, shade)])

    # region select: y<top -> ceil, y>=bot -> floor, else wall.
    y_lt_top = ult(y6, top)
    y_ge_bot = uge(y6, bot)
    lit = mux2_bit(y_lt_top, mux2_bit(y_ge_bot, lit_wall, lit_floor), lit_ceil)
    b.alias_output("lit", lit)
    return b.finish()


# --- reporting helpers --------------------------------------------------------------

def fsm_register_bits() -> Dict[str, int]:
    """The control / datapath register budget of RaycasterFsm (NOT counting the framebuffer).

    These are the m.d.sync registers the machine carries between cycles, the scarce train-bits.
    The 64x32 framebuffer (W*H = 2048 pads) is the OUTPUT signal panel, counted separately.
    """
    def w(hi):
        # bits needed for an Amaranth Signal(range(hi)): the index 0..hi-1.
        return max(1, (hi - 1).bit_length())

    dist_w = w(STEPS + 1)      # a hit step 0..STEPS
    bits = {
        "heading": 5,                  # view angle 0..31
        "cast_col": w(COLS + 2),       # column being cast 0..COLS
        "px": 8,                       # ray x
        "py": 8,                       # ray y
        "step": w(STEPS + 2),          # DDA micro-step counter
        "d_prev": dist_w,              # left-neighbour hit step
        "d_cur": dist_w,               # painted column's hit step
        "d_next": dist_w,              # right-neighbour hit step
        "f_cur": 4,                    # painted column's wall fraction
        "f_next": 4,                   # pipelined next-column wall fraction
        "hit_d": dist_w,               # latched cast result (dist)
        "hit_f": 4,                    # latched cast result (frac)
        "row": w(H + 1),               # paint row 0..H
        "paint_col": w(COLS + 1),      # column being painted 0..COLS
        "tex": 1,                      # texture-enable latch
        "phase": 2,                    # control FSM state
    }
    bits["_control_total"] = sum(v for k, v in bits.items() if not k.startswith("_"))
    bits["_framebuffer"] = W * H
    return bits


def paint_cone_stats() -> Dict[str, int]:
    """NOR-cell counts for the per-pixel paint datapath, lowered to the buildable set."""
    nl = build_paint_cone_netlist()
    low = nl.to_nor()
    s = dict(low.stats())
    return {
        "NOR": s.get("NOR", 0),
        "CONST0": s.get("CONST0", 0),
        "CONST1": s.get("CONST1", 0),
        "total": s.get("_total_cells", 0),
    }
