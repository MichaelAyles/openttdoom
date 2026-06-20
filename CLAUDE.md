# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

openttdoom: a Wolfenstein-3D style raycaster running on a small computer built entirely out
of OpenTTD trains and signals, with the framebuffer drawn as on-map signals. This is a
long-horizon research project. `prompt.md` is the authoritative build brief, read it in full.
`STATUS.md` is the current state (what works, what is stubbed), and `STUCK.md` is the isolated
hard problems. Read those three before starting anything.

No em-dashes in docs or comments, the owner's style is commas and full stops. Never fake an
implementation: if something cannot be verified, leave a `TODO(human):` and an entry in
STUCK.md, do not write plausible non-working code. Verify claims by running them.

## Commands

The dev environment is Windows with Git-Bash / MINGW. Python is `python` (3.12).

- `bash scripts/setup.sh` reproduces the environment: pulls the prebuilt OpenTTD 15.3 win64
  binary and OpenGFX 8.0 into `vendor/`, pip-installs the Python toolchain.
- `bash scripts/run_headless.sh [TICKS]` runs headless OpenTTD (`-vnull:ticks=...`), the M0
  smoke test. The Windows binary is GUI-subsystem so stdout is not piped: success is exit 0
  and wall-clock scaling with the tick count.
- `bash scripts/build.sh` runs the whole toolchain: synth, then place-and-route plus emitter
  on the 4-bit adder, then the test suites.
- `python -m pytest -q` runs all tests (75 currently). Run a single module's tests with
  `python -m pytest place_and_route/test_pnr.py -q`. A repo-root `conftest.py` puts `synth`,
  `place_and_route`, `hdl`, `golden`, `scenarios` on `sys.path`, so tests import contract
  modules by bare name (`from netlist import ...`, `from scenario import ...`).

## Architecture

One compiler from a circuit description down to an OpenTTD map, with a software reference
model alongside to stay honest:

```
  golden model (Python CHIP-8 + viewer)     proves the workload renders, no OpenTTD
        |
  HDL  ->  netlist  ->  place & route  ->  scenario  ->  OpenTTD substrate
 (hdl/)   (synth/)    (place_and_route/)  (scenarios/)   (trains + signals)
```

The two load-bearing contracts every stage is built against (do not casually break them):

- `synth/netlist.py`: the gate-level `Netlist`. A tiny cell library where NOR is the only
  physically buildable gate (universal, NOT is a one-input NOR). It carries the software
  "golden hardware" simulator (`simulate`, `truth_table`), `to_nor()` lowering to the
  buildable set `{NOR, CONST0, CONST1}`, `equivalent()` (port-order independent), and JSON IO.
- `place_and_route/scenario.py`: the spatial `Scenario` (placed cells, routed nets, IO pads,
  framebuffer) with JSON IO and `to_nut()`, which emits the Squirrel data table the GameScript
  reads on load.

Stage notes:

- `golden/` is the M1 oracle: a complete CHIP-8 interpreter (`chip8.py`) plus a headless PNG
  viewer (`viewer.py`), checked against the Timendus reference ROMs by exact framebuffer hash.
- `hdl/` is the Amaranth frontend (behavioural `Adder4` plus a structural `build_adder4_netlist`).
- `synth/` lowers to a buildable NOR netlist. The verified path is the Python `to_nor()`, not
  yosys. yosys is optional: only a stripped WASM yosys is reachable here, the full
  verilog-to-NOR techmap is parked in `synth/adder4.ys` as `TODO(human)`.
- `place_and_route/` places, routes (a crude maze router, unrouted nets recorded honestly),
  emits the scenario, and checks it (`check.py`: DRC, `scenario_to_netlist` reconstruction,
  `verify_equivalence`).
- `scenarios/openttdoom_gs/` is the OpenTTD GameScript. This is the M2 hard piece: the build
  mechanism (Squirrel over binary savegame) is chosen and the data walk is real, but the
  actual NOR gate tile geometry is unsolved and marked `TODO(human)`. See `GATE_DESIGN.md`.

## Where the project stands

M0 and M1 are done and verified. M3 (the toolchain) is verified in software. M4 (the 4-bit
adder) closes through the whole pipeline in software (synth to scenario, logic preserved at
every step). The one thing that does not close is the physical OpenTTD gate: the exact track
and signal geometry of a computing NOR tile is the open research problem. That, the
GameScript runtime verification, the deity/company build-context, and the channel router are
the four things handed to the human. Details and file pointers are in STATUS.md and STUCK.md.

## Out of scope this run (roadmap only, see README.md)

Full CHIP-8 datapath in HDL, running the raycaster on the train machine, the OpenTTD speed
fork, dithering/grayscale/palette colour, trains-as-pixels, rendering real DOOM frames.
