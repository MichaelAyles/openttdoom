"""Tests for the hand-assembled CHIP-8 raycaster (raycaster.py + asm.py).

These prove three things, all by really executing the ROM in the golden
chip8.Chip8 interpreter (no faked frames):

  (a) the tiny assembler round-trips: known mnemonics produce the exact opcodes
      the interpreter decodes, and labels resolve to the right addresses.
  (b) the assembled raycaster ROM, run for real, reproduces the pure-Python
      reference renderer byte for byte, for every heading. The reference is the
      oracle; the ROM matching it is the correctness proof.
  (c) determinism: the raycaster takes no input and uses no randomness, so the
      same heading always yields the same framebuffer hash. This is the property
      a test (and the human eyeballing frames) can rely on.

It also pins the rendered frames by exact framebuffer hash, so a regression in
the interpreter, the assembler, or the raycaster math fails loudly here.
"""

import os

import numpy as np
import pytest

from chip8 import Chip8
import viewer
import raycaster as rc
from asm import Asm

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


# --- (a) assembler sanity ---------------------------------------------------

def test_asm_encodes_known_opcodes():
    a = Asm()
    a.CLS()              # 00E0
    a.LD_imm(0, 0x2A)    # 602A
    a.ADD_imm(1, 0x05)   # 7105
    a.LD_I(0x300)        # A300
    a.DRW(0, 1, 5)       # D015
    a.RET()              # 00EE
    rom = a.assemble()
    words = [(rom[i] << 8) | rom[i + 1] for i in range(0, len(rom), 2)]
    assert words == [0x00E0, 0x602A, 0x7105, 0xA300, 0xD015, 0x00EE]


def test_asm_label_resolves_to_address():
    # a forward JP must encode the resolved absolute address of the label.
    a = Asm()
    a.JP("target")       # at 0x200, two bytes
    a.LD_imm(0, 0x01)    # at 0x202
    a.label("target")    # at 0x204
    a.LD_imm(0, 0x02)
    rom = a.assemble()
    first = (rom[0] << 8) | rom[1]
    assert first == 0x1204, f"JP target encoded as {first:#06x}, expected 0x1204"


def test_asm_here_counts_two_bytes_per_instruction():
    # the address bookkeeping must treat each instruction as two bytes, else
    # labels land on the wrong (odd) addresses and jumps hit garbage.
    a = Asm()
    assert a.here() == 0x200
    a.LD_imm(0, 0)
    assert a.here() == 0x202
    a.db(0xAB)
    assert a.here() == 0x203
    a.align2()
    assert a.here() == 0x204


def test_assembled_rom_runs_in_interpreter():
    # a trivial assembled program must execute and draw, proving asm output is
    # genuinely interpretable, not just plausible bytes.
    a = Asm()
    a.LD_imm(0, 0)       # x = 0
    a.LD_imm(1, 0)       # y = 0
    a.LD_imm(2, 0)       # digit 0
    a.LD_F(2)            # I = font(0)
    a.DRW(0, 1, 5)       # draw it
    a.label("spin")
    a.JP("spin")
    m = Chip8()
    m.load_rom(a.assemble())
    m.run(10)
    assert int(m.display.sum()) > 0


# --- (b) ROM matches the reference oracle -----------------------------------

ALL_HEADINGS = list(range(rc.NUM_ANGLES))


@pytest.mark.parametrize("heading", ALL_HEADINGS)
def test_rom_matches_reference(heading):
    # the real proof: execute the assembled ROM and require the framebuffer to
    # equal the pure-python reference renderer exactly. covers every heading.
    m = rc.render_rom(heading)
    assert not m.halted, f"ROM halted unexpectedly at heading {heading}"
    ref = rc.render_reference(heading)
    assert np.array_equal(m.display, ref), (
        f"heading {heading}: ROM framebuffer diverged from the reference oracle"
    )


def test_rom_uses_only_standard_opcodes():
    # the raycaster must stay within plain CHIP-8 (no XO-CHIP), so it runs on the
    # unmodified golden interpreter and, later, the train machine. running it to
    # completion without halting is the check: the interpreter halts on any
    # opcode it does not implement, so a clean finish means every opcode decoded.
    m = rc.render_rom(0)
    assert not m.halted


# --- (c) determinism --------------------------------------------------------

@pytest.mark.parametrize("heading", [0, 7, 12, 30])
def test_rom_is_deterministic(heading):
    # same heading, two independent runs, identical framebuffer and hash. the
    # raycaster reads no keys and no RNG, so this must hold exactly.
    a = rc.render_rom(heading)
    b = rc.render_rom(heading)
    assert np.array_equal(a.display, b.display)
    assert viewer.display_hash(a) == viewer.display_hash(b)


def test_reference_is_pure_function_of_heading():
    # the oracle itself must be deterministic, independent of any machine state.
    h = 5
    assert np.array_equal(rc.render_reference(h), rc.render_reference(h))


# --- pinned frames (regression guard) ---------------------------------------
# exact framebuffer fingerprints for a few headings, captured from the verified
# ROM execution. these pin both the lit-pixel count and a sha256 of the display
# bytes, so any change to the assembler, interpreter, or raycaster math that
# alters a rendered frame fails here. regenerate intentionally with
# scripts below if the design changes on purpose.
PINNED = {
    # heading: (lit pixels, sha256 of display.tobytes()), captured from the
    # verified ROM execution above.
    0: (1008, "5ad8ea816de67f72d0707dc2ee78a9a6668aa55f433d62f4c6f3b46163259894"),
    2: (704, "4b0a7c99a7b30fdc6bf9701a0be195607796b4419f660770123e1c492cba0abb"),
    7: (944, "3930bbaa45bfc5aaef1b3b29f08b55c0bd0fa39bdd835be5807995994ca73963"),
    12: (1592, "03d2fa1a1f915710eae7f5cefb4d77d878a163eecc5c9a0232c70e99c185e371"),
}


@pytest.mark.parametrize("heading,want", list(PINNED.items()))
def test_rom_frame_pinned(heading, want):
    want_lit, want_hash = want
    m = rc.render_rom(heading)
    lit = int(m.display.sum())
    assert lit == want_lit, f"heading {heading} lit {lit}, expected {want_lit}"
    assert viewer.display_hash(m) == want_hash, (
        f"heading {heading} hash {viewer.display_hash(m)}, expected {want_hash}"
    )


def test_frames_change_as_player_turns():
    # turning the player must change the view. adjacent depth-rich headings must
    # not produce identical framebuffers, else nothing is actually rotating.
    frames = [rc.render_rom(h).display for h in (0, 2, 4, 6, 8)]
    hashes = {f.tobytes() for f in frames}
    assert len(hashes) == len(frames), "some headings rendered identical frames"


def test_render_frames_to_png(tmp_path):
    # render a couple of frames to PNG via the real viewer, proving the whole
    # path (assemble -> execute -> framebuffer -> PNG) works end to end.
    import render_raycaster

    for heading in (0, 8):
        m = rc.render_rom(heading)
        out = tmp_path / f"ray_{heading}.png"
        viewer.save_png(m, str(out))
        assert out.exists() and out.stat().st_size > 0


# --- (d) the enhanced 1-bit oracle (render_reference_hi) --------------------
# A SEPARATE contract from the plain renderer above. render_reference_hi is the
# gorgeous-within-1-bit target the eventual hardware FSM must reproduce bit for
# bit. The plain render_reference / build_rom contract is unchanged and still
# checked above; nothing here touches it. These tests pin the enhanced oracle's
# exact frames (a few headings, both resolutions) by sha256, and prove it is a
# pure deterministic function so it can be the bit-exact reference.

import hashlib


def _hi_hash(frame) -> str:
    return hashlib.sha256(frame.tobytes()).hexdigest()


def test_hi_resolutions_have_expected_shapes():
    # both resolutions are supported: 64x32 (the signal panel) and 96x48.
    lo = rc.render_reference_hi(0, res="lo")
    hi = rc.render_reference_hi(0, res="hi")
    assert lo.shape == (32, 64)
    assert hi.shape == (48, 96)
    assert lo.dtype == np.uint8 and hi.dtype == np.uint8
    # binary framebuffer: every pixel is 0 or 1, this is a 1-bit panel.
    assert set(np.unique(lo)).issubset({0, 1})
    assert set(np.unique(hi)).issubset({0, 1})


@pytest.mark.parametrize("res", ["lo", "hi"])
@pytest.mark.parametrize("heading", [0, 7, 12, 24])
def test_hi_is_deterministic(res, heading):
    # same inputs -> identical framebuffer and identical hash. the oracle reads no
    # input and uses no RNG, so this must hold exactly. it is the property the FSM
    # is later checked against.
    a = rc.render_reference_hi(heading, res=res)
    b = rc.render_reference_hi(heading, res=res)
    assert np.array_equal(a, b)
    assert _hi_hash(a) == _hi_hash(b)


def test_hi_texture_changes_the_frame():
    # the vertical wall texture LUT must actually be wired in: toggling it changes
    # the rendered wall pixels (otherwise it is dead decoration, not a feature).
    on = rc.render_reference_hi(7, res="lo", texture=True)
    off = rc.render_reference_hi(7, res="lo", texture=False)
    assert not np.array_equal(on, off)


def test_hi_frames_change_as_player_turns():
    # turning must change the enhanced view too; adjacent depth-rich headings must
    # not collapse to identical frames.
    frames = [rc.render_reference_hi(h, res="lo") for h in (0, 4, 8, 12, 16)]
    hashes = {f.tobytes() for f in frames}
    assert len(hashes) == len(frames), "some headings rendered identical hi frames"


def test_hi_has_dithered_floor_and_ceiling():
    # the floor and ceiling fills must produce lit pixels in their regions (not a
    # void), so the slab floats inside a room. check a heading whose centre column
    # has a finite-height slice with floor below and ceiling above.
    f = rc.render_reference_hi(7, res="lo")
    h, w = f.shape
    # bottom quarter (floor band) and top region should both carry dither pixels
    # somewhere across the frame.
    assert int(f[3 * h // 4 :, :].sum()) > 0, "no floor dither"
    assert int(f[: h // 4, :].sum()) > 0, "no ceiling dither"


# pinned enhanced-oracle frames: exact fingerprints captured from the verified
# pure renderer. These FREEZE the gorgeous 1-bit target. The hardware FSM in the
# next deliverable is required to reproduce these byte for byte, so a change to
# the enhanced renderer math that alters any frame fails loudly here. Regenerate
# intentionally (only on a deliberate design change) with the helper at the foot
# of raycaster's render path.
PINNED_HI = {
    # (res, heading): (lit pixels, sha256 of frame.tobytes())
    ("lo", 0): (429, "c1ebac5f947929b5d52d64cfc22cff49e17b93b7f1a9501395e3f796bd4448b5"),
    ("lo", 7): (402, "35a2e64af3c12bcd5d0faeef91124eff248bd10bfc4458b40d2964401a3db1b3"),
    ("lo", 12): (847, "cb7184f52060200315e505301a9059fd694fa49dbe679000eff84824e16cdd0f"),
    ("lo", 24): (1057, "837028140e77a326f632e87246ac075d3bd693bb226a176c643e37db2869801b"),
    ("hi", 0): (982, "8dc9111514fadfe702158f4c24556bd34216616eca3dc2e7dc67f5b1c332a9e4"),
    ("hi", 7): (995, "7b26e638137885c4fd5b355979de5289cec1727dc10401043234a57ab86d0291"),
    ("hi", 12): (1983, "e20207a86f958e1683a6a579fc326c8fe86a41ca5d737effd7e96537b612a51d"),
    ("hi", 24): (2459, "54f3f95826c7f02cea803be44b97716f9baa340c13cc24e36cc4fd0c4d7b5138"),
}


@pytest.mark.parametrize("key,want", list(PINNED_HI.items()))
def test_hi_frame_pinned(key, want):
    res, heading = key
    want_lit, want_hash = want
    f = rc.render_reference_hi(heading, res=res)
    lit = int(f.sum())
    assert lit == want_lit, f"{res} h{heading} lit {lit}, expected {want_lit}"
    got = _hi_hash(f)
    assert got == want_hash, f"{res} h{heading} hash {got}, expected {want_hash}"


# --- (e) the PURE-INTEGER 1-bit oracle (render_reference_hw) -----------------
# A THIRD contract, the one the hardware FSM is actually built to match. Unlike
# render_reference_hi (which uses float trig and so cannot be reproduced by a NOR
# netlist bit for bit), render_reference_hw is the SAME integer fixed-point DDA as
# the plain render_reference, with the gorgeous look rebuilt entirely from integer
# LUT lookups keyed off the integer hit-step. Because it is pure integer and
# deterministic, the FSM can reproduce it exactly. These tests prove it is integer
# (no float leaks into the frame: a re-run is byte-identical), supports the 64x32
# panel, wires in every feature, and pin the exact frames by sha256 so a change to
# the integer oracle that alters any frame fails loudly here. The plain
# render_reference / build_rom and the float render_reference_hi contracts above
# are untouched and still checked.

def test_hw_resolutions_have_expected_shapes():
    # the required 64x32 signal panel, plus a 128x64 panel from the same integer
    # math. binary framebuffer, every pixel 0 or 1.
    lo = rc.render_reference_hw(0, res="lo")
    hi = rc.render_reference_hw(0, res="hi")
    assert lo.shape == (32, 64)
    assert hi.shape == (64, 128)
    assert lo.dtype == np.uint8 and hi.dtype == np.uint8
    assert set(np.unique(lo)).issubset({0, 1})
    assert set(np.unique(hi)).issubset({0, 1})


@pytest.mark.parametrize("res", ["lo", "hi"])
@pytest.mark.parametrize("heading", [0, 7, 12, 24])
def test_hw_is_deterministic(res, heading):
    # same inputs -> identical framebuffer and hash. Being PURE INTEGER, this holds
    # exactly and platform-independently (no float rounding), which is precisely the
    # property the FSM is later required to match.
    a = rc.render_reference_hw(heading, res=res)
    b = rc.render_reference_hw(heading, res=res)
    assert np.array_equal(a, b)
    assert _hi_hash(a) == _hi_hash(b)


def test_hw_matches_plain_renderer_hit_distance():
    # the hardware oracle MUST cast with the same integer DDA as render_reference:
    # _cast_hw's hit step is exactly _cast's, so the wall geometry is shared. Check
    # every column of every heading agrees on the hit step (the depth key).
    for heading in range(rc.NUM_ANGLES):
        for col in range(rc.NUM_COLS):
            ang = (heading + rc.COL_ANGLE[col]) % rc.NUM_ANGLES
            step_plain = rc._cast(rc.PLAYER_X, rc.PLAYER_Y, ang)
            step_hw, _frac = rc._cast_hw(rc.PLAYER_X, rc.PLAYER_Y, ang)
            assert step_hw == step_plain, (
                f"heading {heading} col {col}: hw step {step_hw} != plain {step_plain}"
            )


def test_hw_texture_changes_the_frame():
    # the vertical wall texture LUT must be wired in: toggling it changes the wall
    # pixels (otherwise it is dead decoration).
    on = rc.render_reference_hw(7, res="lo", texture=True)
    off = rc.render_reference_hw(7, res="lo", texture=False)
    assert not np.array_equal(on, off)


def test_hw_frames_change_as_player_turns():
    # turning must change the view; adjacent depth-rich headings must not collapse
    # to identical frames.
    frames = [rc.render_reference_hw(h, res="lo") for h in (0, 4, 8, 12, 16)]
    hashes = {f.tobytes() for f in frames}
    assert len(hashes) == len(frames), "some headings rendered identical hw frames"


def test_hw_has_dithered_floor_and_ceiling():
    # the floor and dark ceiling integer fills must produce lit pixels in their
    # regions (not a void), so the slab floats inside a room.
    f = rc.render_reference_hw(7, res="lo")
    h, w = f.shape
    assert int(f[3 * h // 4 :, :].sum()) > 0, "no floor dither"
    assert int(f[: h // 4, :].sum()) > 0, "no ceiling dither"


def test_hw_has_edge_and_depth_seams():
    # the 1px black slice seams and the depth-discontinuity seams must actually cut
    # the frame: with a wall slice present, some interior wall rows must be dark
    # (the seams), so the slab is outlined rather than a solid block.
    f = rc.render_reference_hw(7, res="lo")
    # the slice band around the vertical centre should contain both lit and unlit
    # columns (dither + seams), never a fully solid rectangle.
    h, w = f.shape
    band = f[h // 2 - 2 : h // 2 + 2, :]
    assert int(band.sum()) > 0 and int(band.sum()) < band.size, "no seams/dither in slice band"


# pinned PURE-INTEGER oracle frames: exact fingerprints captured from the verified
# integer renderer. These FREEZE the FSM's bit-exact target. Because the renderer
# is integer-only these hashes are platform-independent. A change to the integer
# oracle math that alters any frame fails loudly here; regenerate only on a
# deliberate design change.
PINNED_HW = {
    # (res, heading): (lit pixels, sha256 of frame.tobytes())
    ("lo", 0): (484, "1e789be89084f9645d6934632a3731eec707f6d64cdd26564a4d7a9eb21a7a6b"),
    ("lo", 7): (535, "975ed3c87de95fff8e14b82403f0f8eb800df02ed40928b1a5b2449638fe31e7"),
    ("lo", 12): (687, "3955292d6d7ffe2269a3dcca54a646f5b70a555c5ec8af5c939bf293485a5b46"),
    ("lo", 24): (962, "e60acf4ae9ad87f358817fca2d02ec3545f03b27ba933449919a73c7b9e402de"),
    ("hi", 0): (2122, "50ca060e00979fb55f3fdc1c64e6677fe0be7857b926dc6575337cda4197e985"),
    ("hi", 7): (2329, "f09a7b966399a79f42144ddaffac9ecc90876f32ab67137861024329f772f159"),
    ("hi", 12): (2937, "d8ee4851a6381f519d41a65bc7ab4a2640d3d6419ef55f47001f382577a08859"),
    ("hi", 24): (3972, "c376166afcb5c4508f7c7833bcdd9ce84af8975d19040d02421dff39c56ca259"),
}


@pytest.mark.parametrize("key,want", list(PINNED_HW.items()))
def test_hw_frame_pinned(key, want):
    res, heading = key
    want_lit, want_hash = want
    f = rc.render_reference_hw(heading, res=res)
    lit = int(f.sum())
    assert lit == want_lit, f"{res} h{heading} lit {lit}, expected {want_lit}"
    got = _hi_hash(f)
    assert got == want_hash, f"{res} h{heading} hash {got}, expected {want_hash}"
