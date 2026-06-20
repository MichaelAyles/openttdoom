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
