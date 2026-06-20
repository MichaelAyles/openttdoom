# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

openttdoom: a Wolfenstein-3D-style raycaster running on a small computer built entirely
out of OpenTTD trains and signals, with the framebuffer rendered as on-map signals. This
is a long-horizon research project. The repo currently contains only `prompt.md`, the
authoritative build brief. Read `prompt.md` in full before doing anything — it defines the
architecture (already decided, do not re-derive), the milestones, and the scope guardrails.

## How the system fits together

The pipeline runs left to right, each stage provable on its own:

1. **Golden model** (`golden/`) — a Python CHIP-8 / XO-CHIP interpreter plus framebuffer
   viewer. Proves the workload (a raycaster ROM) renders with zero OpenTTD involvement.
   CHIP-8's 64x32 monochrome display maps 1:1 onto the signal framebuffer.
2. **HDL** (`hdl/`) — Amaranth (Python) describes the machine and a primitive cell library.
3. **Synthesis** (`synth/`) — yosys lowers the HDL to a netlist of primitive cells.
4. **Place and route** (`place_and_route/`) — positions cells and routes signal nets as
   track, emitting a loadable OpenTTD scenario (`scenarios/`).
5. **Substrate** — OpenTTD itself. Bits are signal states, train presence is the value,
   gates are track, a train on a fixed loop is the clock. Gate geometry comes from the
   openttdcoop wiki (`wiki.openttdcoop.org/Logic`) and zem.fi's logic page — use those
   constructions, do not invent gate geometry from scratch.

The CHIP-8 target was chosen so existing assemblers/emulators/demos let us prove "the
workload runs on the machine" independently of OpenTTD. Heavy math (sin/cos/reciprocal)
lives in lookup tables that become hardwired ROM (free landscape) on the substrate.

## Construction mechanism (M2 decision)

Scenarios are built by a **GameScript** (Squirrel API) that constructs track/signals/trains
when the scenario loads — try this before hand-writing the binary `.sav` chunked format.
The GameScript path is the more tractable one and is the construction mechanism reused by
the place-and-route emitter in M3/M4.

## Milestones (do in order, checkpoint after each)

M0 scaffold + deps → M1 workload renders in golden model → M2 one working gate (NOR/NOT
tile stamp that computes in headless OpenTTD) → M3 toolchain spine (Amaranth→yosys→P&R→
scenario) → M4 4-bit ripple-carry adder end to end. **Stop at the M4 review gate** and write
`STATUS.md`. M2 (the gate tile) is the hardest foundational piece.

## Working rules (from the brief — these override default behavior)

- **Never fake an implementation.** If something doesn't work, leave a clear `TODO(human):`
  and an entry in `STUCK.md` (what you tried, what failed, the exact error). A clear stub
  beats plausible non-working code.
- **Verify every claim.** Run it, show the output. If OpenTTD builds, show it starting. If a
  gate computes, show the input poke and the output flip.
- **Do not thrash.** Make one real attempt at a stuck hard piece; if still blocked, document
  it precisely in `STUCK.md` and move on to scaffolding. Do not burn the run on one piece.
- **Small, single-concern commits.**
- **Docs: markdown, no em-dashes, plain dev-log tone.** Use commas and full stops.
- Respect **Out of scope** (see `prompt.md`): full CHIP-8 datapath in HDL, running the
  raycaster on the train machine, the OpenTTD speed fork, dithering/color, trains-as-pixels,
  real DOOM frames. Stub and roadmap these in `README.md`, do not attempt them.

## Commands

None exist yet. Per the brief, build these under `scripts/` and keep them reproducible:

- `scripts/setup.sh` — pull and build all dependencies (OpenTTD via CMake + OpenGFX/OpenSFX/
  OpenMSX base sets, DOOM source + shareware DOOM1.WAD for reference only, c-octo CHIP-8
  toolchain, `pip install amaranth`, yosys + verilator via oss-cad-suite, pygame/pillow/numpy).
- `scripts/build.sh` — build the project artifacts.
- `scripts/run_headless.sh` — run headless OpenTTD (`openttd -D`); must start with OpenGFX
  and load a test map.

Note: the dev environment is Windows (PowerShell primary). The brief's scripts are `.sh`;
a Bash tool is available, but confirm shell assumptions when authoring them.

## Dependencies live in vendor/

`vendor/openttd/`, `vendor/doom/`, `vendor/chip8/` — pulled deps, gitignored where large.
Fetch only the freely-distributable shareware DOOM1.WAD, never commercial WADs.
