# Raycaster ROM search

The end goal for openttdoom is a Wolfenstein style raycaster running as a CHIP-8
program on the train built machine. This note records the search for an existing
raycaster ROM so we do not write one from scratch if a good one already exists.
Building the raycaster is NOT part of this run, this is just reconnaissance.

## What I looked for

A CHIP-8, SUPER-CHIP, or XO-CHIP ROM that does pseudo-3D / raycast first person
rendering, ideally with source so we can study and retarget it, and ideally plain
CHIP-8 rather than XO-CHIP so it fits the 64x32 monochrome framebuffer that maps
1:1 onto the signal display.

## What exists

There are two real candidates, both verified to exist.

1. Chipenstein 3D, by John Earnest, in the Octo examples repository.
   https://github.com/JohnEarnest/Octo/blob/gh-pages/examples/demos/chipenstein.8o
   Raw source (HTTP 200, 6474 bytes) confirmed at:
   https://raw.githubusercontent.com/JohnEarnest/Octo/gh-pages/examples/demos/chipenstein.8o
   This is the most useful find. It is a work in progress raycast 2.5d shooter
   with full Octo assembly source, a 16x16 map, and a documented raycast routine.
   The header says it "uses PWM techniques to simulate extra colors and must run
   at 1000 cycles/frame", so it is XO-CHIP and leans on high cycle counts and
   color PWM, not a clean monochrome 64x32 fit. Still, the raycast math and the
   map walking loop are exactly the parts we want to reuse.

2. Simple Raycaster (XO-Chip), by Kouzerumatsukite, from an Octojam.
   https://kouzeru.itch.io/simple-raycaster-xo-chip
   An itch.io release. Also XO-CHIP. Source availability not confirmed from the
   itch.io page, would need to be downloaded and checked.

## Assessment

No clean plain-CHIP-8, 64x32 monochrome raycaster turned up. Both candidates are
XO-CHIP and assume the higher XO-CHIP cycle budget and extra colors. That matters
for us because:

- The signal framebuffer is 1-bit monochrome 64x32 (P0), so XO-CHIP color PWM and
  the larger SUPER-CHIP/XO-CHIP 128x64 mode do not map directly. We would target
  the monochrome subset.
- XO-CHIP "1000 cycles/frame" is a software pacing assumption. On the train
  machine, clock rate is whatever the substrate gives us, so that number is not a
  hard constraint, but it does tell us the per frame instruction count is large.

Chipenstein 3D is the clear reference to study. It proves the algorithm fits in
the CHIP-8 instruction set and gives us a working map format and raycast loop.

## Plan for later (do NOT build now)

This is a sketch for the human or a later run, not work for this run.

1. Pull chipenstein.8o into vendor/chip8/ and run it in this golden model to see
   how far the plain interpreter gets. It is XO-CHIP, so first confirm which
   XO-CHIP opcodes it uses (the 00DN scroll ops, F000 long load, plane select,
   audio). Our interpreter is plain CHIP-8 today, so it will likely halt on the
   first XO-CHIP opcode. That tells us exactly what to add.

2. Decide the target tier. Cleanest path for the signal display is a monochrome
   64x32 raycaster. Options, in order of preference:
   a. Strip Chipenstein down to monochrome single plane and 64x32.
   b. Write a minimal new raycaster in Octo from scratch: a small fixed map, one
      ray per screen column (64 columns), distance to wall via DDA grid step,
      column height from a reciprocal lookup table (the math tables become free
      hardwired ROM on the substrate, per the architecture brief), draw vertical
      wall slices with DXYN. No texturing, no color, no sprites.

3. Bake the resulting .ch8 as ROM for the place and route ROM block. The sin /
   cos / reciprocal lookup tables become hardwired landscape, which is the whole
   reason a raycaster was chosen as the workload.

4. Cross check the ROM in the golden model here first (render frames to PNG,
   confirm wall slices look right) before anything touches the train build.

## Sources

- Awesome CHIP-8 index: https://github.com/tobiasvl/awesome-chip-8
- CHIP-8 community links: https://chip-8.github.io/links/
- Chipenstein 3D source: https://github.com/JohnEarnest/Octo/blob/gh-pages/examples/demos/chipenstein.8o
- Simple Raycaster XO-Chip: https://kouzeru.itch.io/simple-raycaster-xo-chip
- Octo IDE / assembler: https://github.com/JohnEarnest/Octo and https://github.com/JohnEarnest/c-octo
