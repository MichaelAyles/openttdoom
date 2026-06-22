"""A minimal Wolfenstein-style raycaster, hand-assembled to a real CHIP-8 ROM.

No existing plain-CHIP-8 64x32 raycaster ROM exists (the known candidates,
Chipenstein 3D and Kouzeru's Simple Raycaster, are XO-CHIP: they need extended
opcodes, 128x64 hires, and colour-plane PWM, none of which map onto the 1-bit
64x32 signal framebuffer, and there is no Octo/c-octo assembler in this
environment to retarget them). So this module builds one from scratch with the
tiny asm.py assembler. The resulting bytes execute for real in the golden
chip8.Chip8 interpreter, using only standard CHIP-8 opcodes, and draw vertical
wall slices that form a recognizable pseudo-3D corridor.

The algorithm is a fixed-point DDA grid raycaster. The contract this module
guarantees, checked in test_raycaster.py:

    render_reference(heading)  -- pure-Python model, the oracle.
    build_rom(heading)         -- assembles a ROM that, run in chip8.Chip8,
                                  produces a framebuffer equal to the reference.

build_rom bakes the heading and the player position into the ROM as immediates,
along with the trig and reciprocal lookup tables, so each frame is a self
contained ROM (the way a hardwired-ROM machine would hold one program). On the
train substrate those tables become hardwired landscape, which is exactly why a
table-driven raycaster was chosen as the workload.

Coordinate scheme (CHIP-8 friendly, one unsigned byte per axis):
  - 16x16 cell map, position in 16th-of-a-cell units, so each axis is 0..255 and
    fits exactly one unsigned byte.
  - cell index = pos >> 4, map byte = MAP[cy*16 + cx].
  - per-angle ray delta stored as magnitude (0..3) plus a sign bit, added or
    subtracted each micro-step because CHIP-8 is unsigned.
  - the map border is a solid wall and the per-step magnitude (max 3) is smaller
    than a cell (16), so a ray always lands in a border cell before it could run
    off the 0..255 numeric range. that means no off-map carry math is needed: the
    DDA just steps and tests the map cell.
  - DDA marches up to STEPS steps; the hit step indexes the reciprocal table for
    the slice height.
"""

from __future__ import annotations

import numpy as np

from asm import Asm
from chip8 import SCREEN_W, SCREEN_H

# --- map and fixed-point constants ------------------------------------------

# 16x16 maze. 1 = wall, 0 = open. thick solid border so every ray terminates.
# the interior is a maze of corridors, pillars and rooms so rotating the view
# reveals walls at a range of depths, which is what makes the pseudo-3D read.
MAP_ROWS = [
    "1111111111111111",
    "1000000000000001",
    "1000000000000001",
    "1011110111101101",
    "1010000000001001",
    "1010111110101001",
    "1010100010101001",
    "1000100010001001",
    "1011101110111101",
    "1001000000100001",
    "1101011110101111",
    "1000010000100001",
    "1011110111101101",
    "1000000000000001",
    "1000000000000001",
    "1111111111111111",
]
MAP_N = 16
MAP = bytes(int(c) for row in MAP_ROWS for c in row)

NUM_ANGLES = 32
STEPS = 48             # max ray length in micro-steps.
SUB = 16               # sub-units per cell; position is 0..255 per axis.
STEP_SCALE = 3         # per-step delta magnitude, < SUB so the border catches rays.

# player position, cell (1,1) centered, in a corner room facing into the maze.
PLAYER_X = 1 * SUB + 8
PLAYER_Y = 1 * SUB + 8

NUM_COLS = 32          # rays cast; each drawn 2 px wide -> 64 px.
HALF_FOV = NUM_ANGLES // 8

# trig tables: per-angle delta magnitude and sign.
DIRX_MAG = [0] * NUM_ANGLES
DIRY_MAG = [0] * NUM_ANGLES
SIGNX = [0] * NUM_ANGLES
SIGNY = [0] * NUM_ANGLES
for _i in range(NUM_ANGLES):
    _a = (_i / NUM_ANGLES) * 2.0 * np.pi
    _dx, _dy = np.cos(_a), np.sin(_a)
    DIRX_MAG[_i] = int(round(abs(_dx) * STEP_SCALE))
    DIRY_MAG[_i] = int(round(abs(_dy) * STEP_SCALE))
    SIGNX[_i] = 1 if _dx < 0 else 0
    SIGNY[_i] = 1 if _dy < 0 else 0

# reciprocal table: hit-step -> slice height. nearer hit (small step) -> taller
# slice. the *5 constant spreads depth across the screen height without saturating
# at the nearest few steps too aggressively.
RECIP = [SCREEN_H] + [
    max(2, min(SCREEN_H, round((SCREEN_H * 5) / d))) for d in range(1, STEPS + 1)
]

# precomputed per-column angle offset (col -> angle delta), so the ROM does not
# need a divide. ang = heading + COL_ANGLE[col], all mod NUM_ANGLES.
COL_ANGLE = [((col * HALF_FOV) // 16 - HALF_FOV) % NUM_ANGLES for col in range(NUM_COLS)]


# --- pure-python reference (the oracle) -------------------------------------

def _cell_solid(cx, cy):
    if cx < 0 or cy < 0 or cx >= MAP_N or cy >= MAP_N:
        return True
    return MAP[cy * MAP_N + cx] == 1


def _cast(px, py, angle):
    dxm, dym = DIRX_MAG[angle], DIRY_MAG[angle]
    sx, sy = SIGNX[angle], SIGNY[angle]
    x, y = px, py
    for step in range(1, STEPS + 1):
        x = (x - dxm) if sx else (x + dxm)
        y = (y - dym) if sy else (y + dym)
        # x,y stay within 0..255 because the solid border is hit first; the ROM
        # relies on that too, so the reference does not special-case the edge.
        if _cell_solid(x >> 4, y >> 4):
            return step
    return STEPS


def render_reference(heading: int, px: int = PLAYER_X, py: int = PLAYER_Y) -> np.ndarray:
    """The oracle framebuffer for a given heading. The ROM must reproduce it."""
    disp = np.zeros((SCREEN_H, SCREEN_W), dtype=np.uint8)
    for col in range(NUM_COLS):
        ang = (heading + COL_ANGLE[col]) % NUM_ANGLES
        dist = _cast(px, py, ang)
        h = RECIP[dist]
        top = (SCREEN_H - h) // 2
        if top < 0:
            top = 0
        bot = top + h
        if bot > SCREEN_H:
            bot = SCREEN_H
        x0 = col * 2
        disp[top:bot, x0] = 1
        disp[top:bot, x0 + 1] = 1
    return disp


# --- the enhanced 1-bit oracle (render_reference_hi) ------------------------
#
# A second, richer oracle. The existing render_reference above is the contract
# the CHIP-8 ROM (build_rom) reproduces and must NOT change. This enhanced
# renderer is a separate, frozen target: the gorgeous-within-1-bit picture the
# eventual hardware FSM (deliverable B) is required to reproduce bit for bit.
#
# It is a pure, deterministic function of (heading, position, resolution): same
# inputs give an identical framebuffer, pinned by sha256 in the tests. It is NOT
# constrained to CHIP-8 opcodes, because the FSM that will reproduce it is custom
# hardware, not a CHIP-8 core. The look is everything 1 bit allows: per-pixel
# Bayer 4x4 ordered dither of wall brightness by hit distance (so distance reads
# as several perceived grey bands), 1px black edge seams at slice top/bottom and
# at column depth discontinuities, dithered floor and ceiling fills that turn the
# floating slabs into a room, and a small vertical wall texture. Every continuous
# quantity (distance->shade, floor row->shade, texture column->bias) is a small
# integer LUT, because on the train substrate a LUT is free hardwired landscape.

# Bayer 4x4 ordered-dither threshold matrix, values 0..15. A pixel of target
# shade s (0..16, 0=black 16=white) is lit where BAYER4[y&3, x&3] < s, so s acts
# as a coverage level and the matrix spreads the lit pixels into the classic
# ordered-dither pattern. 16 distinct s values give up to 17 perceived levels,
# of which the eye resolves 4 to 5 stable grey bands on a 1-bit panel.
BAYER4 = np.array(
    [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    dtype=np.int16,
)
BAYER_LEVELS = 16  # BAYER4 entries are 0..15; shade s in 0..16 -> coverage s/16.

# A finer fixed-point DDA than the ROM uses, so the oracle has smooth depth to
# dither. Position is still 0..255 (16th-of-a-cell), but the march sub-steps the
# cell at SUBSTEPS per cell so the hit distance is a real distance, not a coarse
# step index. This is software, it is allowed to be more precise than the ROM.
HI_SUBSTEPS = 64           # ray micro-steps per cell along the longer axis.
HI_MAX_CELLS = 20          # how many cells a ray may cross before giving up.

# Distance -> wall shade LUT. Index is the perpendicular hit distance in
# sixteenths-of-a-cell (0..HI_DIST_MAX-1), value is a wall brightness 0..16 fed
# to the Bayer compare. Near walls are bright (high coverage, mostly lit), far
# walls are dark (low coverage, sparse dither), which is the depth cue. The curve
# is hand-tuned: a bright near plateau then a smooth roll-off so several bands are
# visible across the corridor depth, never fully black (min 2) so far walls still
# read as wall, not void.
HI_DIST_MAX = 256          # distance index is clamped into 0..255 (one byte).


def _build_dist_shade_lut():
    lut = np.empty(HI_DIST_MAX, dtype=np.int16)
    for d in range(HI_DIST_MAX):
        # d is in sixteenths of a cell. map to cells, then an inverse falloff.
        # the near plateau is capped at 13 (not 16) so even the closest walls keep
        # a visible Bayer texture instead of whiting out, and the floor stays the
        # only fully-bright surface. min 2 keeps far walls reading as wall.
        cells = d / 16.0
        shade = 13.0 / (1.0 + cells * 0.85)
        lut[d] = int(max(2, min(13, round(shade))))
    return lut


DIST_SHADE = _build_dist_shade_lut()

# Floor / ceiling shade LUT. Index is distance-from-the-horizon in pixels (row
# distance from screen centre), value is a shade 0..16 for the Bayer compare.
# The nearest floor/ceiling rows (far from the horizon, near the player) are the
# brightest; rows near the horizon fade to near-black. Ceiling is dimmer than the
# floor so the two planes read as different surfaces, like Wolfenstein's grey
# ceiling over a lighter floor.
FLOOR_SHADE_MAX = 64       # row distance index range.


def _build_plane_shade_lut(near, far, gamma=1.0):
    lut = np.empty(FLOOR_SHADE_MAX, dtype=np.int16)
    for r in range(FLOOR_SHADE_MAX):
        t = (r / (FLOOR_SHADE_MAX - 1)) ** gamma
        shade = far + (near - far) * t
        lut[r] = int(max(0, min(16, round(shade))))
    return lut


# floor reads as a lit ground plane fading toward the horizon. ceiling is a dark
# sky/vault: it stays near-black except for the rows nearest the player, so the
# top of the frame is a clean dark field that the dithered walls sit against,
# which is what makes the m_v2 prototype read. gamma>1 pushes the fade so the
# bright band hugs the near edge instead of smearing up to the horizon.
FLOOR_SHADE = _build_plane_shade_lut(near=11, far=1, gamma=1.6)
CEIL_SHADE = _build_plane_shade_lut(near=4, far=0, gamma=2.2)

# Vertical wall texture LUT. Index is the wall-hit coordinate within the cell
# (0..15, the fractional position along the wall face), value is a small signed
# brightness bias added to the wall shade before the Bayer compare. A shallow
# repeating groove pattern so flat walls gain a faint vertical banding, like
# panelled brick, without overpowering the distance shading. Hardwired LUT.
WALL_TEX = np.array(
    [2, 1, 0, -1, -2, -1, 0, 1, 2, 1, 0, -1, -2, -1, 0, 1],
    dtype=np.int16,
)

# Resolution presets. The machine framebuffer is 64x32 (the signal panel), but
# the oracle also supports a 96x48 target for the higher-resolution build. Both
# are pinned. Each ray is drawn `colw` pixels wide to fill the width.
HI_RES = {
    "lo": {"w": 64, "h": 32, "cols": 64, "colw": 1},
    "hi": {"w": 96, "h": 48, "cols": 96, "colw": 1},
}


def _cast_hi(px, py, angle_rad):
    """Sub-stepped DDA returning (perp_dist_16ths, wall_frac_0_15, hit) for the
    enhanced oracle. perp distance is in sixteenths of a cell (an integer, so the
    result is exact and platform-independent), wall_frac is the texture coordinate
    along the hit face (0..15), hit is True if a wall was found. Pure integer-ish
    math kept deterministic: all the trig is folded into per-call dx,dy in
    sixteenths-of-a-cell per substep, computed once with rounding so two runs of
    the same heading give identical integers."""
    dx = np.cos(angle_rad)
    dy = np.sin(angle_rad)
    # step length per micro-step in sixteenths-of-a-cell, scaled so the longer
    # axis advances one substep-fraction of a cell each step.
    inv = HI_SUBSTEPS
    sx = dx / inv
    sy = dy / inv
    # walk in cell space using float for the march, but quantise the start so the
    # path is reproducible; positions are exact float ops on the same inputs.
    cx = px / 16.0
    cy = py / 16.0
    steps = HI_MAX_CELLS * HI_SUBSTEPS
    prev_cx, prev_cy = cx, cy
    for _ in range(steps):
        cx += sx
        cy += sy
        mx = int(np.floor(cx))
        my = int(np.floor(cy))
        if _cell_solid(mx, my):
            # which face did we cross to enter this cell? compare which integer
            # boundary flipped between prev and now to pick the texture axis.
            crossed_x = int(np.floor(cx)) != int(np.floor(prev_cx))
            crossed_y = int(np.floor(cy)) != int(np.floor(prev_cy))
            if crossed_x and not crossed_y:
                frac = cy - np.floor(cy)
            elif crossed_y and not crossed_x:
                frac = cx - np.floor(cx)
            else:
                # both flipped on the same step (corner): pick the dominant axis.
                frac = (cy - np.floor(cy)) if abs(dx) >= abs(dy) else (cx - np.floor(cx))
            # perpendicular distance: project the travelled vector onto the view
            # direction is unnecessary here because we cast per-column already; the
            # straight-line distance is corrected for fisheye by the caller via the
            # column angle. distance in sixteenths-of-a-cell:
            ddx = cx - (px / 16.0)
            ddy = cy - (py / 16.0)
            dist_cells = (ddx * ddx + ddy * ddy) ** 0.5
            wall_frac = int(frac * 16.0) & 0x0F
            return dist_cells, wall_frac, True
        prev_cx, prev_cy = cx, cy
    return float(HI_MAX_CELLS), 0, False


def render_reference_hi(
    heading: int,
    px: int = PLAYER_X,
    py: int = PLAYER_Y,
    res: str = "lo",
    texture: bool = True,
) -> np.ndarray:
    """The ENHANCED 1-bit oracle: the gorgeous-within-1-bit frame.

    Pure and deterministic: the returned (h, w) uint8 0/1 framebuffer is a fixed
    function of (heading, px, py, res, texture). This is a SEPARATE contract from
    render_reference / build_rom (which are unchanged); this frame is the frozen
    target the hardware FSM must reproduce bit for bit.

    heading is the integer angle index 0..NUM_ANGLES-1 (same convention as the
    plain renderer) so the two oracles share a heading space. res is "lo" (64x32,
    the signal panel) or "hi" (96x48). texture toggles the vertical wall texture.
    """
    cfg = HI_RES[res]
    w, h, cols, colw = cfg["w"], cfg["h"], cfg["cols"], cfg["colw"]
    disp = np.zeros((h, w), dtype=np.uint8)

    half = h // 2
    # field of view: 90 degrees, matching the plain renderer's HALF_FOV span.
    base = (heading % NUM_ANGLES) / NUM_ANGLES * 2.0 * np.pi
    fov = (2.0 * HALF_FOV / NUM_ANGLES) * 2.0 * np.pi  # angular width of the view.

    # first pass: per-column ray cast -> (slice top, slice bottom, wall shade,
    # wall texture frac, raw distance index). distances feed the depth-seam test.
    tops = np.empty(cols, dtype=np.int32)
    bots = np.empty(cols, dtype=np.int32)
    wsh = np.empty(cols, dtype=np.int16)
    wfr = np.empty(cols, dtype=np.int16)
    dix = np.empty(cols, dtype=np.int32)

    for c in range(cols):
        # column camera offset across the FOV, -0.5..+0.5, with fisheye-correcting
        # ray angle. classic camera-plane parametrisation.
        camera = (c + 0.5) / cols - 0.5
        ray = base + camera * fov
        dist_cells, frac, hit = _cast_hi(px, py, ray)
        # fisheye correction: perpendicular distance = ray distance * cos(camera).
        perp = dist_cells * np.cos(camera * fov)
        if perp < 0.02:
            perp = 0.02
        # slice height: an inverse-distance projection, the proportionality
        # constant chosen so a wall one cell away fills most of the screen.
        line_h = int((h * 1.1) / perp)
        top = half - line_h // 2
        bot = half + line_h // 2
        if top < 0:
            top = 0
        if bot > h:
            bot = h
        tops[c] = top
        bots[c] = bot
        wfr[c] = frac
        # distance index in sixteenths-of-a-cell, clamped to the LUT.
        di = int(perp * 16.0)
        if di < 0:
            di = 0
        if di >= HI_DIST_MAX:
            di = HI_DIST_MAX - 1
        dix[c] = di
        wsh[c] = DIST_SHADE[di]

    # depth-discontinuity seam: a column is a "depth edge" if its neighbour is at
    # a markedly different distance (a corner / occlusion boundary). Such columns
    # get a black vertical seam so walls at different depths separate cleanly.
    DEPTH_SEAM_THRESH = 12  # sixteenths-of-a-cell jump that counts as an edge.
    depth_edge = np.zeros(cols, dtype=bool)
    for c in range(cols):
        left = dix[c - 1] if c > 0 else dix[c]
        right = dix[c + 1] if c < cols - 1 else dix[c]
        if abs(int(dix[c]) - int(left)) >= DEPTH_SEAM_THRESH or abs(
            int(dix[c]) - int(right)
        ) >= DEPTH_SEAM_THRESH:
            depth_edge[c] = True

    # second pass: paint. ceiling, floor, then the wall slice with Bayer dither,
    # finally the 1px black seams.
    for c in range(cols):
        top = int(tops[c])
        bot = int(bots[c])
        shade = int(wsh[c])
        if texture:
            shade = max(2, min(16, shade + int(WALL_TEX[wfr[c]])))
        x0 = c * colw
        x1 = x0 + colw

        for x in range(x0, x1):
            bxcol = x & 3
            # ceiling: rows above the slice top, dithered by distance from horizon.
            for y in range(0, top):
                ri = half - 1 - y
                if ri < 0:
                    ri = 0
                if ri >= FLOOR_SHADE_MAX:
                    ri = FLOOR_SHADE_MAX - 1
                s = int(CEIL_SHADE[ri])
                if s > 0 and BAYER4[y & 3, bxcol] < s:
                    disp[y, x] = 1
            # floor: rows below the slice bottom.
            for y in range(bot, h):
                ri = y - half
                if ri < 0:
                    ri = 0
                if ri >= FLOOR_SHADE_MAX:
                    ri = FLOOR_SHADE_MAX - 1
                s = int(FLOOR_SHADE[ri])
                if s > 0 and BAYER4[y & 3, bxcol] < s:
                    disp[y, x] = 1
            # wall slice: Bayer-dithered by the column's wall shade.
            for y in range(top, bot):
                if BAYER4[y & 3, bxcol] < shade:
                    disp[y, x] = 1

        # 1px black edge seams at the slice top and bottom, so every wall slab is
        # outlined against floor/ceiling. clear the boundary rows across the
        # column's width.
        if bot > top:
            if top < h:
                disp[top, x0:x1] = 0
            if bot - 1 >= 0 and bot - 1 < h:
                disp[bot - 1, x0:x1] = 0

        # depth-discontinuity seam: a black vertical line over the slice extent.
        if depth_edge[c]:
            disp[top:bot, x0:x1] = 0

    return disp


# --- the PURE-INTEGER 1-bit oracle (render_reference_hw) ---------------------
#
# render_reference_hi above is gorgeous but reads np.cos/np.sin/np.floor in its
# per-column march and float multiplies in its per-pixel paint. A NOR netlist
# cannot reproduce a float bit for bit, so render_reference_hi can never be the
# hardware FSM's exact target. render_reference_hw is the answer: the SAME look,
# rebuilt as a PURE-INTEGER, deterministic function so the FSM can match it
# exactly.
#
# The contract:
#   - the per-column ray cast is the SAME integer fixed-point DDA as the plain
#     render_reference: _cast_hw is _cast plus an integer wall-fraction readout.
#     No float, no np.cos/np.sin/np.floor anywhere in the per-column or per-pixel
#     path. The only float lives in the module-load LUT builders, which on the
#     train substrate are hardwired landscape (free constant tiles), exactly like
#     DIRX_MAG/RECIP already are.
#   - the gorgeous upgrades are all expressed as INTEGER LUT lookups keyed off the
#     integer hit-step `dist` (1..STEPS) the DDA returns:
#       * slice height from RECIP[dist] (the plain renderer's own table),
#       * wall brightness from HW_DIST_SHADE[dist] (step -> shade LUT),
#       * Bayer 4x4 ordered dither of the wall (threshold compare, integer),
#       * 1px black edge seams at slice top and bottom,
#       * black vertical seams at column depth discontinuities (integer |jump| of
#         the hit-step between neighbouring columns vs a threshold),
#       * dithered floor and a dark dithered ceiling (row-distance -> shade LUTs),
#       * an optional integer vertical wall texture LUT keyed off the integer
#         wall-hit fraction.
#   - it supports the 64x32 "lo" panel (and a 128x64 "hi" for completeness). It is
#     a pure function of (heading, px, py, res, texture), pinned by sha256 below.
#
# Because every quantity is an integer LUT indexed by an integer, the eventual
# hardware FSM (a register + NOR datapath that walks the same DDA and the same
# tables) can reproduce this frame bit for bit. This is the FSM's bit-exact
# target, the integer sibling of render_reference_hi.

# Step -> wall shade LUT. Index is the integer DDA hit-step `dist` (0..STEPS),
# value is a wall brightness 0..16 fed to the Bayer compare. Near hits (small
# step) are bright, far hits dark, the depth cue. Capped at 13 so even near walls
# keep a visible Bayer texture (the floor is the only fully-bright surface) and
# floored at 2 so the farthest walls still read as wall, not void. Built once at
# module load (float here is fine, it is a hardwired constant table); the
# per-pixel path only ever INDEXES it with the integer step.
HW_STEP_SHADE_MAX = STEPS + 1


def _build_step_shade_lut():
    lut = [0] * HW_STEP_SHADE_MAX
    for d in range(HW_STEP_SHADE_MAX):
        # d is the integer micro-step count to the hit. STEP_SCALE units per step,
        # SUB units per cell, so cells travelled ~= d * STEP_SCALE / SUB.
        cells = (d * STEP_SCALE) / SUB
        shade = 13.0 / (1.0 + cells * 0.85)
        lut[d] = int(max(2, min(13, round(shade))))
    return lut


HW_STEP_SHADE = _build_step_shade_lut()

# Bayer 4x4 ordered-dither threshold matrix as a plain integer list-of-lists
# (values 0..15). A target shade s (0..16) lights a pixel where BAYER4_HW[y&3][x&3]
# < s, so s is a coverage level spread into the classic ordered-dither pattern.
# Kept independent of the numpy BAYER4 above so this oracle is self-contained and
# obviously integer.
BAYER4_HW = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]

# Floor / ceiling shade LUTs. Index is the row distance from the horizon (screen
# centre) in pixels, value is a shade 0..16 for the Bayer compare. Nearest rows
# (far from the horizon) are brightest; rows near the horizon fade out. The
# ceiling is dimmer than the floor so the two planes read as different surfaces.
# Built per call for the requested height (the index range scales with the panel),
# but the build is integer-from-an-integer-fraction so it is exact and
# deterministic.
def _build_plane_shade_lut_int(rows: int, near: int, far: int, gamma_num: int,
                               gamma_den: int):
    """A plane shade LUT with `rows` entries, fading from `near` (row 0, closest)
    to `far` (last row, the horizon). The gamma is a rational gamma_num/gamma_den
    applied as integer arithmetic on a 0..1024 fixed-point t, so no float and the
    same rows give identical integers on any platform."""
    lut = [0] * max(1, rows)
    denom = max(1, rows - 1)
    for r in range(rows):
        # t in 0..1024 fixed point.
        t = (r * 1024) // denom
        # integer pow approximation: t^(gamma) for gamma = gamma_num/gamma_den,
        # done by repeated integer multiply for the integer part and a single
        # linear blend for the fractional part. gammas used here are 8/5 and 11/5,
        # both in [1, 3], so one or two multiplies plus a fractional blend suffice.
        whole = gamma_num // gamma_den
        frac_num = gamma_num - whole * gamma_den       # remaining /gamma_den
        # t_pow_whole = t^whole in the same 0..1024 scale.
        tp = 1024
        for _ in range(whole):
            tp = (tp * t) // 1024
        # one extra factor of t^(frac_num/gamma_den), linearly interpolated between
        # t^0 (=1024) and t^1 (=t) by frac_num/gamma_den. integer blend.
        extra = (1024 * (gamma_den - frac_num) + t * frac_num) // gamma_den
        tg = (tp * extra) // 1024                       # t^gamma, 0..1024
        shade = far + ((near - far) * tg) // 1024
        lut[r] = int(max(0, min(16, shade)))
    return lut


# Vertical wall texture LUT. Index is the integer wall-hit fraction within the
# cell (0..15), value is a small signed brightness bias added before the Bayer
# compare, a shallow repeating groove so flat walls gain faint vertical banding.
HW_WALL_TEX = [2, 1, 0, -1, -2, -1, 0, 1, 2, 1, 0, -1, -2, -1, 0, 1]

# Resolution presets for the integer oracle. "lo" is the 64x32 signal panel (the
# required target). "hi" is a 128x64 panel built from the same integer math, for
# completeness. Each ray is drawn `colw` pixels wide to fill the width.
HW_RES = {
    "lo": {"w": SCREEN_W, "h": SCREEN_H, "cols": NUM_COLS, "colw": SCREEN_W // NUM_COLS},
    "hi": {"w": 128, "h": 64, "cols": 64, "colw": 2},
}


def _cast_hw(px, py, angle):
    """The SAME integer DDA as _cast, returning (hit_step, wall_frac).

    hit_step is the integer micro-step index of the wall hit (1..STEPS), exactly
    what _cast returns. wall_frac (0..15) is the sub-cell coordinate along the hit
    face, read straight out of the low nibble of the integer ray position, so the
    texture coordinate is pure integer too. The texture axis is chosen by which
    integer cell coordinate changed on the hitting step (an integer >>4 compare),
    mirroring _cast_hi's face pick without any float. No np.cos/np.sin/np.floor."""
    dxm, dym = DIRX_MAG[angle], DIRY_MAG[angle]
    sx, sy = SIGNX[angle], SIGNY[angle]
    x, y = px, py
    for step in range(1, STEPS + 1):
        prev_cx, prev_cy = x >> 4, y >> 4
        x = (x - dxm) if sx else (x + dxm)
        y = (y - dym) if sy else (y + dym)
        cx, cy = x >> 4, y >> 4
        if _cell_solid(cx, cy):
            crossed_x = cx != prev_cx
            crossed_y = cy != prev_cy
            if crossed_x and not crossed_y:
                frac = y & 0x0F          # vertical face: texture by the y position
            elif crossed_y and not crossed_x:
                frac = x & 0x0F          # horizontal face: texture by x
            else:
                # corner (both or neither flipped): pick the dominant ray axis by
                # the integer delta magnitudes, an integer compare.
                frac = (y & 0x0F) if dxm >= dym else (x & 0x0F)
            return step, frac
    return STEPS, 0


def render_reference_hw(
    heading: int,
    px: int = PLAYER_X,
    py: int = PLAYER_Y,
    res: str = "lo",
    texture: bool = True,
) -> np.ndarray:
    """The PURE-INTEGER gorgeous 1-bit oracle: render_reference's integer DDA with
    the render_reference_hi look, rebuilt with integer LUTs so a NOR/FSM datapath
    can reproduce it bit for bit.

    Pure and deterministic: the returned (h, w) uint8 0/1 framebuffer is a fixed
    function of (heading, px, py, res, texture), pinned by sha256 in the tests.
    NO float, np.cos, np.sin or np.floor appears in the per-column or per-pixel
    path; the only float is in the module-load shade-LUT builders, which are
    hardwired constant landscape on the substrate.

    heading is the integer angle index 0..NUM_ANGLES-1 (the same heading space as
    render_reference). res is "lo" (64x32, the signal panel, the required target)
    or "hi" (128x64). texture toggles the vertical wall texture LUT.

    This is a SEPARATE contract from render_reference / build_rom (unchanged) and
    from render_reference_hi (the float look). This frame is the FSM's bit-exact
    integer target.
    """
    cfg = HW_RES[res]
    w, h, cols, colw = cfg["w"], cfg["h"], cfg["cols"], cfg["colw"]
    disp = np.zeros((h, w), dtype=np.uint8)
    half = h // 2

    # plane shade LUTs sized to this panel's half-height, built once per call from
    # integer math. floor brighter and reaching higher than the dark ceiling.
    floor_rows = h - half
    ceil_rows = half if half > 0 else 1
    floor_shade = _build_plane_shade_lut_int(max(1, floor_rows), near=11, far=1,
                                             gamma_num=8, gamma_den=5)
    ceil_shade = _build_plane_shade_lut_int(max(1, ceil_rows), near=4, far=0,
                                            gamma_num=11, gamma_den=5)

    # height scaling: the plain RECIP is tuned for SCREEN_H=32, so scale it to this
    # panel by an integer ratio h/SCREEN_H (1 for "lo", 2 for "hi").
    hscale = h // SCREEN_H if h >= SCREEN_H else 1

    # first pass: per-column integer ray cast -> (hit_step, slice top/bottom, wall
    # shade, wall frac). The hit step is the integer depth key for the seam test.
    dists = [0] * cols
    tops = [0] * cols
    bots = [0] * cols
    wsh = [0] * cols
    wfr = [0] * cols
    for c in range(cols):
        ang = (heading + COL_ANGLE[(c * NUM_COLS) // cols]) % NUM_ANGLES
        dist, frac = _cast_hw(px, py, ang)
        line_h = RECIP[dist] * hscale
        if line_h > h:
            line_h = h
        top = (h - line_h) // 2
        if top < 0:
            top = 0
        bot = top + line_h
        if bot > h:
            bot = h
        dists[c] = dist
        tops[c] = top
        bots[c] = bot
        wfr[c] = frac
        wsh[c] = HW_STEP_SHADE[dist]

    # depth-discontinuity seam: a column is a depth edge if a neighbour's integer
    # hit-step differs by at least the threshold (a corner / occlusion boundary).
    DEPTH_SEAM_THRESH = 4   # micro-step jump that counts as a depth edge.
    depth_edge = [False] * cols
    for c in range(cols):
        left = dists[c - 1] if c > 0 else dists[c]
        right = dists[c + 1] if c < cols - 1 else dists[c]
        if abs(dists[c] - left) >= DEPTH_SEAM_THRESH or \
           abs(dists[c] - right) >= DEPTH_SEAM_THRESH:
            depth_edge[c] = True

    # second pass: paint ceiling, floor, then the Bayer-dithered wall slice, then
    # the 1px black seams and the depth seam. Every test is an integer compare.
    for c in range(cols):
        top, bot = tops[c], bots[c]
        shade = wsh[c]
        if texture:
            shade = max(2, min(16, shade + HW_WALL_TEX[wfr[c] & 0x0F]))
        x0 = c * colw
        x1 = x0 + colw
        for x in range(x0, x1):
            bx = x & 3
            # ceiling: rows above the slice top, dithered by distance from horizon.
            for y in range(0, top):
                ri = half - 1 - y
                if ri < 0:
                    ri = 0
                if ri >= len(ceil_shade):
                    ri = len(ceil_shade) - 1
                s = ceil_shade[ri]
                if s > 0 and BAYER4_HW[y & 3][bx] < s:
                    disp[y, x] = 1
            # floor: rows below the slice bottom.
            for y in range(bot, h):
                ri = y - half
                if ri < 0:
                    ri = 0
                if ri >= len(floor_shade):
                    ri = len(floor_shade) - 1
                s = floor_shade[ri]
                if s > 0 and BAYER4_HW[y & 3][bx] < s:
                    disp[y, x] = 1
            # wall slice: Bayer-dithered by the column's wall shade.
            for y in range(top, bot):
                if BAYER4_HW[y & 3][bx] < shade:
                    disp[y, x] = 1

        # 1px black edge seams at the slice top and bottom, outlining the slab.
        if bot > top:
            if 0 <= top < h:
                disp[top, x0:x1] = 0
            if 0 <= bot - 1 < h:
                disp[bot - 1, x0:x1] = 0

        # depth-discontinuity seam: a black vertical line over the slice extent.
        if depth_edge[c] and bot > top:
            disp[top:bot, x0:x1] = 0

    return disp


# --- the ROM builder --------------------------------------------------------
#
# Register map for the assembled program:
#   V0  scratch / draw x
#   V1  scratch / draw y (slice top), reused
#   V2  ray position x (0..127)
#   V3  ray position y (0..127)
#   V4  dx magnitude (this column)
#   V5  dy magnitude
#   V6  sign x (0/1)
#   V7  sign y (0/1)
#   V8  column counter (0..31)
#   V9  step counter (DDA)
#   VA  current angle for this column
#   VB  scratch (cell index / map byte / height / loop)
#   VC  scratch
#   VD  slice draw counter
#   VE  scratch
#   VF  flags (carry/borrow/collision), never hold state across ops
#
# Tables are appended after the code and addressed via labels. A 1x1 "dot"
# sprite (one byte 0x80) is drawn repeatedly to paint a vertical slice, two
# columns wide.


def build_rom(heading: int, px: int = PLAYER_X, py: int = PLAYER_Y) -> bytes:
    a = Asm()

    # register name aliases for readability.
    SX, SY = 2, 3          # ray pos x,y
    DXM, DYM = 4, 5        # delta magnitudes
    SGX, SGY = 6, 7        # signs
    COL = 8                # column counter
    STEP = 9               # dda step counter
    ANG = 0xA              # angle
    T0 = 0xB               # scratch
    T1 = 0xC               # scratch
    DRAWN = 0xD            # slice rows drawn
    T2 = 0xE               # scratch

    # ---- entry ----
    a.CLS()

    # COL = 0
    a.LD_imm(COL, 0)

    a.label("col_loop")

    # --- compute angle = (heading + COL_ANGLE[COL]) & 31 ---
    # T0 = COL_ANGLE[COL] : I = colangle_table + COL, load into V0.
    a.LD_I_label("colangle")
    a.LD(0, COL)            # V0 = COL
    a.ADD_I(0)             # I += COL
    a.LOAD(0)             # V0 = COL_ANGLE[COL]
    a.LD(ANG, 0)           # ANG = V0
    a.ADD_imm(ANG, heading & 0xFF)
    a.LD_imm(T0, 31)
    a.AND(ANG, T0)         # ANG &= 31

    # --- load the four trig entries for ANG ---
    # DXM = DIRX_MAG[ANG]
    a.LD_I_label("dirx")
    a.LD(0, ANG)
    a.ADD_I(0)
    a.LOAD(0)
    a.LD(DXM, 0)
    # DYM = DIRY_MAG[ANG]
    a.LD_I_label("diry")
    a.LD(0, ANG)
    a.ADD_I(0)
    a.LOAD(0)
    a.LD(DYM, 0)
    # SGX = SIGNX[ANG]
    a.LD_I_label("signx")
    a.LD(0, ANG)
    a.ADD_I(0)
    a.LOAD(0)
    a.LD(SGX, 0)
    # SGY = SIGNY[ANG]
    a.LD_I_label("signy")
    a.LD(0, ANG)
    a.ADD_I(0)
    a.LOAD(0)
    a.LD(SGY, 0)

    # --- init ray position to the player, step counter to 0 ---
    a.LD_imm(SX, px & 0xFF)
    a.LD_imm(SY, py & 0xFF)
    a.LD_imm(STEP, 0)

    # --- DDA march ---
    a.label("dda")
    a.ADD_imm(STEP, 1)
    # if STEP > STEPS -> stop at STEPS (hit). compare STEP == STEPS+1.
    a.SNE_imm(STEP, STEPS + 1)
    a.JP("dda_done_max")

    # advance x: if SGX then SX -= DXM else SX += DXM. no off-map check is
    # needed: positions stay in 0..255 because the solid border cell is always
    # hit before a step could push the byte past its range (DXM <= 3 < 16).
    a.SE_imm(SGX, 0)
    a.JP("x_neg")
    a.ADD(SX, DXM)         # positive step.
    a.JP("x_ok")
    a.label("x_neg")
    a.SUB(SX, DXM)         # negative step.
    a.label("x_ok")

    # advance y, same structure.
    a.SE_imm(SGY, 0)
    a.JP("y_neg")
    a.ADD(SY, DYM)
    a.JP("y_ok")
    a.label("y_neg")
    a.SUB(SY, DYM)
    a.label("y_ok")

    # --- cell lookup: index = cy*16 + cx, cy = SY>>4, cx = SX>>4 ---
    # since the map is 16 wide, index = (SY & 0xF0) | (SX >> 4): the high nibble
    # is cy*16 and the low nibble is cx. compute SX>>4 with four SHR (the golden
    # default shift_use_vy shifts VY into VX, so shift in place with y == x).
    a.LD(T1, SX)
    a.SHR(T1, T1)
    a.SHR(T1, T1)
    a.SHR(T1, T1)
    a.SHR(T1, T1)          # T1 = cx (0..15)
    a.LD(T2, SY)
    a.LD_imm(T0, 0xF0)
    a.AND(T2, T0)          # T2 = SY & 0xF0 = cy*16
    a.OR(T2, T1)           # T2 = cy*16 + cx (cx is the low nibble)
    # I = map + index ; load byte into V0.
    a.LD_I_label("map")
    a.LD(0, T2)
    a.ADD_I(0)
    a.LOAD(0)             # V0 = MAP[index]
    a.SE_imm(0, 0)         # if V0 == 0 (empty) skip the hit jump
    a.JP("hit")           # nonzero -> wall.
    # empty cell, keep marching.
    a.JP("dda")

    a.label("dda_done_max")
    a.LD_imm(STEP, STEPS)  # clamp to max distance.
    # fallthrough to hit.

    a.label("hit")
    # --- height = RECIP[STEP] ---
    a.LD_I_label("recip")
    a.LD(0, STEP)
    a.ADD_I(0)
    a.LOAD(0)
    a.LD(T0, 0)            # T0 = height (2..32)

    # --- top = (32 - height) / 2 ; clamp >= 0 ---
    a.LD_imm(T1, SCREEN_H)
    a.SUB(T1, T0)          # T1 = 32 - height (>=0 since height<=32). VF set.
    a.SHR(T1, T1)          # T1 = top = (32-height)/2
    # DRAWN counter = height, draw y starts at top.
    a.LD(DRAWN, T0)        # rows remaining to draw
    a.LD(0, COL)
    a.SHL(0, 0)            # V0 = col*2 = screen x.
    a.LD(T2, 0)            # T2 = base x for this column.

    # I -> the dot sprite once; it does not move.
    a.LD_I_label("dot")

    a.label("draw_loop")
    # if DRAWN == 0 done.
    a.SE_imm(DRAWN, 0)
    a.JP("draw_one")
    a.JP("col_next")
    a.label("draw_one")
    # draw at (T2, T1) and (T2+1, T1): two 1px-wide columns.
    a.LD(0, T2)
    a.LD(1, T1)
    a.DRW(0, 1, 1)
    a.ADD_imm(0, 1)
    a.DRW(0, 1, 1)
    a.ADD_imm(T1, 1)       # next row down.
    a.LD_imm(0, 1)
    a.SUB(DRAWN, 0)        # DRAWN -= 1
    a.JP("draw_loop")

    a.label("col_next")
    a.ADD_imm(COL, 1)
    a.SE_imm(COL, NUM_COLS)
    a.JP("col_loop")

    # done: spin forever so the framebuffer is stable for capture.
    a.label("end")
    a.JP("end")

    # --- data tables -------------------------------------------------------
    a.align2()
    a.label("dot")
    a.db(0x80)             # single top-left pixel sprite.

    a.align2()
    a.label("colangle")
    a.db(*COL_ANGLE)

    a.align2()
    a.label("dirx")
    a.db(*DIRX_MAG)
    a.label("diry")
    a.db(*DIRY_MAG)
    a.label("signx")
    a.db(*SIGNX)
    a.label("signy")
    a.db(*SIGNY)

    a.align2()
    a.label("recip")
    a.db(*RECIP)

    a.align2()
    a.label("map")
    a.db(*MAP)

    return a.assemble()


# a comfortable instruction budget: the worst-case frame (all 32 columns marching
# the full STEPS before a hit, then drawing full-height slices) lands well under
# this. measured peak is about 30k instructions, so 200k is generous headroom and
# still runs in a fraction of a second.
RENDER_CYCLES = 200_000


def run_rom_bytes(rom: bytes, cycles: int = RENDER_CYCLES):
    """Run an assembled ROM in the golden interpreter until it reaches its idle
    spin loop (or the cycle cap), and return the machine. Deterministic: the
    raycaster takes no input and uses no randomness, so the framebuffer is a pure
    function of the baked-in heading."""
    from chip8 import Chip8

    m = Chip8()
    m.load_rom(rom)
    prev = -1
    idle = 0
    for _ in range(cycles):
        if m.halted:
            break
        # the program ends in `JP end`, a 2-cycle self-loop where pc oscillates
        # on a single instruction. once pc stops advancing across several steps,
        # the frame is finished and the framebuffer will not change again.
        if m.pc == prev:
            idle += 1
            if idle >= 4:
                break
        else:
            idle = 0
        prev = m.pc
        m.step()
    return m


def render_rom(heading: int, px: int = PLAYER_X, py: int = PLAYER_Y):
    """Build and run the raycaster ROM for a heading, returning the machine whose
    display holds the rendered frame."""
    return run_rom_bytes(build_rom(heading, px, py))
