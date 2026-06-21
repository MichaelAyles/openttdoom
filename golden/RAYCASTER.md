# Raycaster ROM, search and build

The end goal for openttdoom is a Wolfenstein style raycaster running as a CHIP-8
program on the train built machine. This note first records the search for an
existing raycaster ROM, then documents the minimal raycaster that was actually
built and verified in the golden model.

## What was built (the deliverable)

A minimal Wolfenstein style raycaster, hand assembled to a real plain CHIP-8 ROM
that executes in the golden interpreter (`golden/chip8.py`) and draws a
recognizable pseudo-3D maze view to the 64x32 framebuffer. No interpreter changes
were needed: it uses only standard CHIP-8 opcodes.

Files:

- `golden/asm.py` is a tiny CHIP-8 assembler (labels, the standard opcode set).
  Every mnemonic maps to the exact opcode `chip8.py` decodes, so its output runs
  for real on the golden interpreter. Unit tested in `test_raycaster.py`.
- `golden/raycaster.py` builds the raycaster ROM and carries the pure-Python
  reference renderer that is the oracle. `build_rom(heading)` assembles a ROM,
  `render_reference(heading)` is the oracle, `render_rom(heading)` runs the ROM
  in the interpreter and returns the machine.
- `golden/render_raycaster.py` renders a turn sweep to `golden/out/ray_*.png`.
- `golden/test_raycaster.py` proves, by really executing the ROM, that it matches
  the reference for all 32 headings, is deterministic, and stays on standard
  opcodes, and pins exact framebuffer hashes.

How to run:

```
cd golden
python render_raycaster.py          # writes golden/out/ray_00.png .. ray_15.png
python -m pytest test_raycaster.py -q
```

### The algorithm

A fixed-point DDA grid raycaster, kept deliberately CHIP-8 friendly because the
machine has no multiply, no divide, and only 8-bit registers.

- Map: a 16x16 cell maze, 1 bit per cell, with a solid border. Corridors,
  pillars and rooms so rotating the view reveals walls at a range of depths.
- Position: measured in 16th-of-a-cell units, so each axis is 0..255 and fits one
  unsigned byte. Cell index is `pos >> 4`, the map byte is `MAP[(SY & 0xF0) | (SX >> 4)]`.
- Rays: 32 columns across a 90 degree field of view, each drawn 2 pixels wide to
  fill the 64 pixel width. The per column angle offset is a baked table so the ROM
  needs no divide.
- Per ray DDA: a per-angle delta `(dx, dy)` is stored as magnitude (0..3) plus a
  sign bit, because CHIP-8 is unsigned. Each micro-step adds or subtracts the
  magnitude and tests the map cell. The border is solid and the step magnitude is
  smaller than a cell, so a ray always lands in a border cell before it could run
  off the 0..255 numeric range, which means no off-map carry math is needed.
- Wall height: the DDA step count at the hit indexes a reciprocal table that gives
  the slice height (near hit, tall slice). The slice is drawn centered as a
  vertical run of a 1x1 dot sprite.

The trig (`DIRX_MAG`, `DIRY_MAG`, `SIGNX`, `SIGNY`), the per column angle table,
and the reciprocal table are all baked into the ROM as data. On the train
substrate these become hardwired landscape, which is exactly why a table-driven
raycaster was chosen as the workload (the architecture brief).

### Verification

`render_reference` is the oracle and `render_rom` runs the assembled bytes in the
unmodified `chip8.Chip8`. `test_raycaster.py` requires them to be byte-for-byte
equal for all 32 headings, asserts run-to-run determinism (no input, no RNG), and
pins exact framebuffer sha256 fingerprints for several headings. The frames in
`golden/out/ray_*.png` are produced by that same real execution path, not drawn
by hand. The ROM is 652 bytes and a frame finishes in about 30k instructions.

## Why a ROM was hand built rather than reused

No clean plain CHIP-8, 64x32 monochrome raycaster ROM exists. The two real
candidates are both XO-CHIP and do not map onto the 1-bit 64x32 signal display:

1. Chipenstein 3D, by John Earnest, in the Octo examples repository.
   https://github.com/JohnEarnest/Octo/blob/gh-pages/examples/demos/chipenstein.8o
   A work in progress raycast 2.5d shooter with full Octo source, a 16x16 map and
   a documented raycast routine. Its header says it "uses PWM techniques to
   simulate extra colors and must run at 1000 cycles/frame", so it is XO-CHIP and
   leans on color-plane PWM and high cycle counts, not a monochrome 64x32 fit.
2. Simple Raycaster (XO-Chip), by Kouzerumatsukite, from an Octojam.
   https://kouzeru.itch.io/simple-raycaster-xo-chip
   Also XO-CHIP.

Both need extended XO-CHIP opcodes the golden interpreter does not implement
(`F000 NNNN` long load I, `FN01` plane select, `00DN/00FB/00FC` scroll, `00FF`
hires), 128x64 hires, and color planes. Retargeting Chipenstein to monochrome
64x32 would mean rewriting it in Octo and reassembling, and no Octo or c-octo
assembler was installed in this environment at the time. So the tractable, honest
path was to write a small raycaster from scratch with the tiny `asm.py` assembler,
which is what was done. (Note: the box does in fact have a C/C++ compiler, MSVC 2022,
so c-octo could be built later if a richer XO-CHIP path is wanted, see STUCK.md.)

This is a deliberate, documented choice (option b of the brief's two paths):
extending the interpreter with unverified XO-CHIP opcodes purely to run a color
PWM demo that then has to be stripped back to monochrome anyway is more risk and
less payoff than a small, fully verified plain-CHIP-8 raycaster that already maps
1:1 onto the signal framebuffer.

## Roadmap (not built this run)

The raycaster here is a static-frame-per-heading demo: each frame bakes its
heading into a fresh ROM. A later run can:

- Make it interactive: read the keypad (`EX9E`/`EXA1`) to turn and move the
  player inside one ROM, instead of one ROM per heading.
- Add player translation (forward/back/strafe), not just rotation.
- Texture or shade walls by distance once a grayscale or dithered display path
  exists (out of scope now, the display is 1-bit P0).
- Bake the ROM into the place-and-route ROM block so the lookup tables become
  hardwired landscape on the train substrate.

## Sources

- Awesome CHIP-8 index: https://github.com/tobiasvl/awesome-chip-8
- CHIP-8 community links: https://chip-8.github.io/links/
- Chipenstein 3D source: https://github.com/JohnEarnest/Octo/blob/gh-pages/examples/demos/chipenstein.8o
- Simple Raycaster XO-Chip: https://kouzeru.itch.io/simple-raycaster-xo-chip
- Octo IDE / assembler: https://github.com/JohnEarnest/Octo and https://github.com/JohnEarnest/c-octo
- Cowgod's CHIP-8 opcode reference (used to match asm.py encodings to chip8.py):
  http://devernay.free.fr/hacks/chip8/C8TECH10.HTM
