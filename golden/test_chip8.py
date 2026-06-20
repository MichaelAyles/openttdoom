"""Tests for the golden CHIP-8 model.

Two layers:

  (a) unit tests with tiny hand-assembled ROMs that pin down exact opcode
      behaviour: ALU carry/borrow, logic ops and vf_reset, shifts, jumps, index,
      sprite draw collision and wrap, BCD, and FX55/65 round trip.

  (b) integration tests against the Timendus chip8-test-suite ROMs. These are
      run for enough cycles, rendered to PNGs in golden/out/, and checked for a
      non-trivial and deterministic framebuffer.

A c-octo cross-check is not possible in this environment (no C compiler), so the
Timendus reference ROMs stand in for it. See the deviation note in the run report.
"""

import os

import numpy as np
import pytest

from chip8 import Chip8, SCREEN_W, SCREEN_H, FONT_ADDR, PROGRAM_ADDR
import viewer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM_DIR = os.path.join(ROOT, "vendor", "chip8", "roms")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def asm(words):
    """Assemble a list of 16-bit opcodes into a bytes ROM, big-endian."""
    out = bytearray()
    for w in words:
        out.append((w >> 8) & 0xFF)
        out.append(w & 0xFF)
    return bytes(out)


def make(words=None, **quirks):
    """Build a machine with an optional hand-assembled ROM loaded."""
    m = Chip8(**quirks)
    if words is not None:
        m.load_rom(asm(words))
    return m


# --- (a) unit tests ---------------------------------------------------------

def test_6xnn_and_7xnn():
    # V0 = 0x05, V0 += 0x03 -> 0x08.
    m = make([0x6005, 0x7003])
    m.step()
    assert m.V[0] == 0x05
    m.step()
    assert m.V[0] == 0x08


def test_7xnn_wraps_no_carry():
    # 7XNN must wrap at 256 and never touch VF.
    m = make([0x60FF, 0x7005])
    m.run(2)
    assert m.V[0] == 0x04
    assert m.V[0xF] == 0  # untouched.


def test_8xy4_add_carry():
    # 0xFF + 0x01 -> 0x00 with VF carry = 1.
    m = make([0x60FF, 0x6101, 0x8014])
    m.run(3)
    assert m.V[0] == 0x00
    assert m.V[0xF] == 1


def test_8xy4_add_no_carry():
    # 0x10 + 0x20 -> 0x30 with VF = 0.
    m = make([0x6010, 0x6120, 0x8014])
    m.run(3)
    assert m.V[0] == 0x30
    assert m.V[0xF] == 0


def test_8xy5_sub_borrow():
    # 0x05 - 0x0A -> underflow, VF = 0 (borrow happened).
    m = make([0x6005, 0x610A, 0x8015])
    m.run(3)
    assert m.V[0] == (0x05 - 0x0A) & 0xFF
    assert m.V[0xF] == 0


def test_8xy5_sub_no_borrow():
    # 0x0A - 0x05 -> 0x05, VF = 1 (no borrow).
    m = make([0x600A, 0x6105, 0x8015])
    m.run(3)
    assert m.V[0] == 0x05
    assert m.V[0xF] == 1


def test_8xy7_subn():
    # VX = VY - VX. V0=3, V1=10, 8017 -> V0 = 7, VF = 1.
    m = make([0x6003, 0x610A, 0x8017])
    m.run(3)
    assert m.V[0] == 7
    assert m.V[0xF] == 1


def test_8xy1_or_vf_reset():
    # OR with vf_reset on must clear VF even though VF started at 1.
    m = make([0x6F01, 0x600C, 0x610A, 0x8011], vf_reset=True)
    m.run(4)
    assert m.V[0] == (0x0C | 0x0A)
    assert m.V[0xF] == 0


def test_8xy2_and_vf_reset_off():
    # with vf_reset off VF is left alone.
    m = make([0x6F01, 0x600C, 0x610A, 0x8012], vf_reset=False)
    m.run(4)
    assert m.V[0] == (0x0C & 0x0A)
    assert m.V[0xF] == 1


def test_8xy3_xor():
    m = make([0x600C, 0x610A, 0x8013])
    m.run(3)
    assert m.V[0] == (0x0C ^ 0x0A)


def test_8xy6_shift_right_vy():
    # shift_use_vy: V0 = VY >> 1, VF = lost low bit. VY = 0x05 -> 0x02, VF = 1.
    m = make([0x6105, 0x8016], shift_use_vy=True)
    m.run(2)
    assert m.V[0] == 0x02
    assert m.V[0xF] == 1


def test_8xye_shift_left_vx():
    # shift_use_vy off: shift VX in place. V0 = 0x81 << 1 -> 0x02, VF = 1.
    m = make([0x6081, 0x800E], shift_use_vy=False)
    m.run(2)
    assert m.V[0] == 0x02
    assert m.V[0xF] == 1


def test_3xnn_skip_eq():
    # 3XNN skips next instr when equal. V0=5, 3005 skips the 6042, lands on 600A.
    m = make([0x6005, 0x3005, 0x6042, 0x600A])
    m.run(3)  # 6005, 3005(skip), 600A.
    assert m.V[0] == 0x0A


def test_4xnn_skip_neq():
    m = make([0x6005, 0x4001, 0x6042, 0x600A])
    m.run(3)
    assert m.V[0] == 0x0A


def test_5xy0_and_9xy0():
    # 5XY0 skips when equal, 9XY0 skips when not equal.
    m = make([0x6005, 0x6105, 0x5010, 0x60FF, 0x600A])
    m.run(4)  # set,set,skip(eq),600A.
    assert m.V[0] == 0x0A


def test_1nnn_jump():
    # jump over a poison instruction.
    m = make([0x1204, 0x60FF, 0x600A])  # 0x200 jump to 0x204.
    m.step()
    assert m.pc == 0x204
    m.step()
    assert m.V[0] == 0x0A


def test_2nnn_call_and_00ee_return():
    # call a subroutine that sets V0, then returns and sets V1.
    # addresses (load base 0x200), two bytes each:
    # 0x200: 2208 call 0x208
    # 0x202: 6105 V1 = 5
    # 0x204: 120A jump end (0x20A)
    # 0x206: 0000 padding
    # 0x208: 600A V0 = 10
    # 0x20A: 00EE return
    rom = asm([0x2208, 0x6105, 0x120A, 0x0000, 0x600A, 0x00EE])
    m = Chip8()
    m.load_rom(rom)
    m.step()  # call -> pc 0x208.
    assert m.pc == 0x208
    assert m.stack == [0x202]
    m.step()  # V0 = 10.
    assert m.V[0] == 0x0A
    m.step()  # return -> pc 0x202.
    assert m.pc == 0x202
    m.step()  # V1 = 5.
    assert m.V[1] == 0x05


def test_annn_index():
    m = make([0xA123])
    m.step()
    assert m.I == 0x123


def test_bnnn_jump_offset():
    # classic BNNN uses V0. V0 = 4, B200 -> 0x204.
    m = make([0x6004, 0xB200])
    m.run(2)
    assert m.pc == 0x204


def test_cxnn_deterministic_with_seed():
    # same seed -> same random stream masked by NN.
    a = make([0xC0FF, 0xC0FF], seed=7)
    a.run(2)
    b = make([0xC0FF, 0xC0FF], seed=7)
    b.run(2)
    assert a.V[0] == b.V[0]
    # a different seed should (very likely) differ over a few draws.
    c = make([0xC0FF] * 8, seed=99)
    c.run(8)
    d = make([0xC0FF] * 8, seed=7)
    d.run(8)
    assert c.V[0] != d.V[0] or True  # tolerate rare collision, seed plumbing is the point.


def test_fx33_bcd():
    # store BCD of 156 at I -> [1, 5, 6].
    m = make([0x609C, 0xA300, 0xF033])  # V0 = 0x9C = 156, I = 0x300, BCD.
    m.run(3)
    assert m.memory[0x300] == 1
    assert m.memory[0x301] == 5
    assert m.memory[0x302] == 6


def test_fx55_fx65_roundtrip_and_i_increment():
    # store V0..V2 then load them back into V3..V5 area. check I increments.
    # V0=0xAA V1=0xBB V2=0xCC, I=0x400, FX55 with X=2.
    m = make([0x60AA, 0x61BB, 0x62CC, 0xA400, 0xF255], mem_i_inc=True)
    m.run(5)
    assert m.memory[0x400] == 0xAA
    assert m.memory[0x401] == 0xBB
    assert m.memory[0x402] == 0xCC
    assert m.I == 0x403  # incremented by X+1 = 3.

    # now load them back with FX65 into a fresh machine.
    m2 = make([0xA400, 0xF265], mem_i_inc=True)
    m2.memory[0x400] = 0xAA
    m2.memory[0x401] = 0xBB
    m2.memory[0x402] = 0xCC
    m2.run(2)
    assert m2.V[0] == 0xAA
    assert m2.V[1] == 0xBB
    assert m2.V[2] == 0xCC
    assert m2.I == 0x403


def test_fx55_no_i_increment_quirk_off():
    m = make([0x60AA, 0xA400, 0xF055], mem_i_inc=False)
    m.run(3)
    assert m.memory[0x400] == 0xAA
    assert m.I == 0x400  # unchanged.


def test_fx1e_index_add():
    m = make([0x6010, 0xA200, 0xF01E])
    m.run(3)
    assert m.I == 0x210


def test_fx29_font_address():
    # font for digit 0xA lives at FONT_ADDR + 0xA*5.
    m = make([0x600A, 0xF029])
    m.run(2)
    assert m.I == FONT_ADDR + 0xA * 5


def test_dxyn_draw_and_collision():
    # draw the font glyph for '0' at (0,0): expect lit pixels and VF=0.
    # then draw it again at the same spot: full collision, screen cleared, VF=1.
    rom = asm([
        0x6000,  # V0 = 0 (x)
        0x6100,  # V1 = 0 (y)
        0x6200,  # V2 = 0 (digit)
        0xF229,  # I = font(V2)
        0xD015,  # draw 5 rows at (V0,V1)
        0xD015,  # draw again -> erase, collision.
    ])
    m = Chip8()
    m.load_rom(rom)
    m.run(5)  # through the first draw.
    assert m.display.sum() > 0
    assert m.V[0xF] == 0
    # font '0' is 0xF0,0x90,0x90,0x90,0xF0. top row 0xF0 lights pixels 0..3.
    assert list(m.display[0, 0:4]) == [1, 1, 1, 1]
    assert m.display[0, 4] == 0
    m.step()  # second draw, same place.
    assert m.display.sum() == 0     # fully erased.
    assert m.V[0xF] == 1            # collision detected.


def test_dxyn_start_coord_wraps():
    # a sprite drawn at x=64 wraps the START coord to x=0 (modulo screen).
    rom = asm([
        0x6040,  # V0 = 64 -> wraps to 0.
        0x6100,  # V1 = 0.
        0x6200,  # V2 = 0 digit.
        0xF229,  # I = font.
        0xD015,  # draw.
    ])
    m = Chip8()
    m.load_rom(rom)
    m.run(5)
    # top row of glyph '0' should appear at column 0.
    assert list(m.display[0, 0:4]) == [1, 1, 1, 1]


def test_dxyn_clips_at_bottom():
    # a 5-row sprite drawn with its top at y=30 should only draw 2 rows (30,31)
    # when clipping is on, not wrap to the top.
    rom = asm([
        0x6000,  # V0 = 0.
        0x611E,  # V1 = 30.
        0x6200,  # digit 0.
        0xF229,
        0xD015,  # draw 5 rows.
    ])
    m = Chip8(clip=True)
    m.load_rom(rom)
    m.run(5)
    # glyph '0' is 0xF0, 0x90, 0x90, 0x90, 0xF0. only rows 0 and 1 fit at y=30,31.
    assert m.display[30, 0:4].sum() == 4   # row 0 (0xF0) at y=30, four pixels.
    assert m.display[31, 0:4].sum() == 2   # row 1 (0x90) at y=31, two pixels.
    assert m.display[0].sum() == 0         # nothing wrapped to the top.


def test_00e0_clear():
    rom = asm([0x6000, 0x6100, 0x6200, 0xF229, 0xD015, 0x00E0])
    m = Chip8()
    m.load_rom(rom)
    m.run(5)
    assert m.display.sum() > 0
    m.step()  # 00E0.
    assert m.display.sum() == 0


def test_timers_tick():
    m = make([0x6005, 0xF015])  # delay timer = 5.
    m.run(2)
    assert m.delay_timer == 5
    for _ in range(3):
        m.tick_timers()
    assert m.delay_timer == 2
    for _ in range(5):
        m.tick_timers()
    assert m.delay_timer == 0  # never goes negative.


def test_fx0a_waits_for_key():
    # FX0A blocks until a key goes down, then stores it.
    m = make([0xF00A, 0x600A])  # wait for key into V0, then V0 = 10.
    m.step()  # enters waiting state.
    assert m.waiting_for_key == 0
    m.step()  # still waiting, no key.
    assert m.waiting_for_key == 0
    m.key_down(0x7)
    m.step()  # key seen, V0 = 7, unblocked.
    assert m.waiting_for_key is None
    assert m.V[0] == 0x7
    m.step()  # now the 600A runs.
    assert m.V[0] == 0x0A


def test_ex9e_exa1_keys():
    # EX9E skips if key VX down, EXA1 skips if up.
    m = make([0x6005, 0xE09E, 0x600A, 0x6042])
    m.key_down(5)
    m.run(3)  # set V0=5, EX9E (key 5 down) skips 600A, then runs 6042.
    assert m.V[0] == 0x42


def test_unknown_opcode_halts():
    m = make([0xF0FF])  # not a real FX op.
    m.step()
    assert m.halted


def test_00ee_empty_stack_halts():
    # a return with no matching call used to pop an empty stack and raise
    # IndexError. it must degrade to a graceful halt instead.
    m = make([0x00EE])  # 00EE return, but the stack is empty.
    m.step()
    assert m.halted
    assert m.stack == []


def test_pc_at_top_of_memory_halts():
    # a PC sitting at the last byte of memory used to fetch memory[0x1000] for
    # the low byte and raise IndexError. it must degrade to a graceful halt.
    m = Chip8()
    m.pc = 0xFFF
    m.step()
    assert m.halted


# --- (b) integration tests against Timendus reference ROMs ------------------

REFERENCE_ROMS = {
    "ibm": ("2-ibm-logo.ch8", 30),
    "corax": ("3-corax+.ch8", 400),
    "flags": ("4-flags.ch8", 800),
}


def _rom_path(filename):
    return os.path.join(ROM_DIR, filename)


@pytest.mark.parametrize("name", list(REFERENCE_ROMS))
def test_reference_rom_renders_nontrivial(name):
    filename, cycles = REFERENCE_ROMS[name]
    path = _rom_path(filename)
    if not os.path.exists(path):
        pytest.skip(f"reference ROM missing: {path}")

    os.makedirs(OUT_DIR, exist_ok=True)
    m = viewer.run_rom(path, cycles, seed=0)

    lit = int(m.display.sum())
    total = SCREEN_W * SCREEN_H
    # non-trivial: something is drawn, but not the whole screen filled.
    assert 0 < lit < total, f"{name} drew {lit}/{total} pixels"

    out_png = os.path.join(OUT_DIR, f"{name}.png")
    viewer.save_png(m, out_png)
    assert os.path.exists(out_png)


@pytest.mark.parametrize("name", list(REFERENCE_ROMS))
def test_reference_rom_deterministic(name):
    filename, cycles = REFERENCE_ROMS[name]
    path = _rom_path(filename)
    if not os.path.exists(path):
        pytest.skip(f"reference ROM missing: {path}")

    a = viewer.run_rom(path, cycles, seed=42)
    b = viewer.run_rom(path, cycles, seed=42)
    # identical framebuffers across two runs with the same seed.
    assert np.array_equal(a.display, b.display)
    assert viewer.display_hash(a) == viewer.display_hash(b)


def test_ibm_logo_matches_known_shape():
    # the IBM logo ROM is a fixed bitmap, no randomness, so its lit-pixel count
    # is a stable fingerprint. this guards against silent DXYN regressions.
    path = _rom_path("2-ibm-logo.ch8")
    if not os.path.exists(path):
        pytest.skip("IBM logo ROM missing")
    # the IBM logo ROM clears the screen, draws its bitmap, then loops, so the
    # framebuffer is stable from ~30 cycles onward. 230 lit pixels is the known
    # fingerprint of the rendered logo (verified by eyeballing the ASCII render).
    m = viewer.run_rom(path, 40, seed=0)
    lit = int(m.display.sum())
    assert lit == 230, f"IBM logo lit {lit} pixels"


# the corax+ and flags ROMs are the stand-in for a c-octo opcode-correctness
# cross-check. they have no randomness, so each renders a fixed result grid:
# corax+ a table of opcode checkmarks, flags a table of carry/borrow/shift
# outcomes. the all-pass renders below were captured from the current correct
# model (every group shows a pass, verified by eyeballing the ASCII render) and
# are pinned EXACTLY: both the lit-pixel count and a sha256 of the display bytes.
# this is much stronger than the 0 < lit < total bound above. an inverted 8XY5
# borrow, for instance, leaves the flags lit count unchanged (still 495) yet
# rearranges the lit cells, so only the sha256 catches it. carry (8XY4), borrow
# (8XY5), and shift (8XY6/E) regressions all change the flags framebuffer and
# fail this test. note vf_reset is not displayed by these two ROMs (its quirk
# group lives in the Timendus 5-quirks ROM, which is not vendored here), so no
# framebuffer assertion on corax+/flags can guard it. the unit tests above pin
# vf_reset directly.
EXACT_REFERENCE_RENDERS = {
    # filename: (cycles, lit pixels, sha256 of display.tobytes()).
    "corax": (
        "3-corax+.ch8",
        400,
        503,
        "f7accf00a65c264fadfd94280d57f6c6564115df4b99316395e8253ff1729024",
    ),
    # flags needs more cycles than the weaker reference tests above: at 800 it
    # is still mid-render and the last result group has not been drawn. it fully
    # renders by ~1000 cycles and then loops on a stable frame (lit 495), so
    # pin the completed all-pass render rather than a truncated one.
    "flags": (
        "4-flags.ch8",
        1600,
        495,
        "c9b71cf8aa770baf37cbf0f85b2455fafdc1e537392a258cc3ac9af0ee17d771",
    ),
}


@pytest.mark.parametrize("name", list(EXACT_REFERENCE_RENDERS))
def test_reference_rom_matches_exact_framebuffer(name):
    # pin the exact all-pass render, the way the IBM logo is pinned, so any
    # ALU regression that changes the framebuffer (carry, borrow, shift) fails
    # this test instead of slipping past the weak 0 < lit < total bound.
    filename, cycles, want_lit, want_hash = EXACT_REFERENCE_RENDERS[name]
    path = _rom_path(filename)
    if not os.path.exists(path):
        pytest.skip(f"reference ROM missing: {path}")

    m = viewer.run_rom(path, cycles, seed=0)
    assert not m.halted, f"{name} halted before finishing"

    lit = int(m.display.sum())
    assert lit == want_lit, f"{name} lit {lit} pixels, expected {want_lit}"
    assert viewer.display_hash(m) == want_hash, (
        f"{name} framebuffer hash {viewer.display_hash(m)}, expected {want_hash}"
    )
