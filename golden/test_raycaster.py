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
