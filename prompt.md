# openttdoom build brief

Paste this into Claude Code, or drop it in the repo as `CLAUDE.md` and tell Claude Code "follow the brief in CLAUDE.md."

## Mission

Build the skeleton and toolchain spine for openttdoom: a Wolfenstein-3D-style raycaster running on a small computer constructed entirely out of OpenTTD trains and signals, with the framebuffer rendered as on-map signals. This is a long research project. Your job this run is to stand up the scaffolding, prove the pieces that can be proven cheaply, and push toward one specific de-risking milestone (a 4-bit adder running end to end inside OpenTTD). You are NOT building a working DOOM this run. A human will take over for the tricky bits once the skeleton is in place.

## The architecture (already decided, do not re-derive)

- **Substrate.** Bits are signal states, train presence is the value, gates are track. Synchronous clocked design (a train on a fixed loop is the clock). Reference gate constructions exist at the openttdcoop wiki (`wiki.openttdcoop.org/Logic`) and zem.fi's OpenTTD logic page. Use these for gate geometry, do not invent your own from scratch.
- **Target machine.** A CHIP-8 / XO-CHIP class VM, chosen so we inherit existing assemblers, emulators, and demos and can prove "the workload runs on the machine" independently of OpenTTD. CHIP-8's native 64x32 monochrome display maps 1:1 onto the signal framebuffer.
- **The program.** A raycaster compiled to a CHIP-8 ROM. Heavy math (sin, cos, reciprocal) lives in lookup tables, which become hardwired ROM (free landscape) on the substrate.
- **Toolchain.** HDL (Amaranth, Python) describing the machine, synthesised by yosys to a netlist of primitive cells, then place-and-routed into an OpenTTD scenario. The CHIP-8 ROM is baked as ROM.
- **Display.** Framebuffer is 1-bit signals on the map (signals-as-pixels, P0). Trains-as-pixels is a later stretch. A Python viewer reads the framebuffer out of the sim for clean frames and for the capture-and-replay video. Colour and Bayer dithering are out of scope this run.
- **Speed.** A forked headless OpenTTD (stripped tick loop, fixed routes, uncapped speed) is how this eventually runs fast. The fork is human-led and out of scope this run.

## Your scope for THIS run

Do milestones M0 to M4 below, in order, checkpointing after each. Stop at the M4 review gate. Stub and document everything in "Out of scope," do not attempt it.

## Hard rules

1. **Never fake an implementation.** If something does not work, leave a clear `TODO(human):` and an entry in `STUCK.md` describing what you tried, what failed, and the exact error. A clear stub beats plausible non-working code.
2. **Verify everything you claim.** Run it, show the output. If you say OpenTTD builds, show it starting. If you say a gate computes, show the input poke and the output change.
3. **Do not thrash.** The foundational hard piece (a working gate tile stamp) is genuinely tricky. Make a real attempt, and if you are still blocked after that, document precisely what you tried in `STUCK.md` and move on to scaffolding the rest. Do not burn the whole run on one stuck piece.
4. **Small, labelled commits.** One concern per commit.
5. **Docs in markdown, no em-dashes, plain dev-log tone**, so they match the owner's style. Use commas and full stops, not em-dashes.
6. **End with a `STATUS.md`**: what works, what is stubbed, and the tricky bits isolated for the human, with file pointers.

## Repo structure to create

```
openttdoom/
  README.md                architecture overview + how to build/run
  STATUS.md                end-of-run status (you write this last)
  STUCK.md                 isolated hard problems for the human
  vendor/                  pulled dependencies (gitignored where large)
    openttd/               OpenTTD source + build
    doom/                  DOOM source + shareware WAD (reference only)
    chip8/                 CHIP-8 toolchain + ROMs
  golden/                  Python CHIP-8 interpreter + framebuffer viewer
  hdl/                     Amaranth machine description + primitive cell library
  synth/                   yosys scripts, netlist output
  place_and_route/         netlist -> OpenTTD scenario
  scenarios/               generated/hand-built .sav or GameScript test cases
  scripts/                 setup.sh, build.sh, run_headless.sh
```

## Dependencies to pull and build

- **OpenTTD**: clone `github.com/OpenTTD/OpenTTD`, build with CMake. You also MUST fetch a free base graphics set or it will not start: get **OpenGFX** (and OpenSFX/OpenMSX) from BaNaNaS or `github.com/OpenTTD/OpenGFX`. Confirm the dedicated/headless server runs (`openttd -D`).
- **DOOM (reference only)**: clone `github.com/id-Software/DOOM` (original GPL source) or `github.com/chocolate-doom/chocolate-doom` for a buildable port, and fetch the freely-distributable **shareware DOOM1.WAD** only (not the commercial WADs). We use this for the look and the 256-colour palette, not to run it.
- **CHIP-8 toolchain**: John Earnest's Octo / c-octo (`github.com/JohnEarnest/c-octo`) for the assembler and a reference emulator. Search for an existing CHIP-8 or XO-CHIP raycaster / pseudo-3D ROM. If none is suitable, note it and scaffold a minimal raycaster in Octo assembly as a later task, do not block M1 on it.
- **HDL/synth**: `pip install amaranth`, install **yosys** and **verilator** (the oss-cad-suite bundle is the easiest way to get both).
- **Viewer**: Python with pygame or pillow, plus numpy.

Put all of this behind `scripts/setup.sh` so it is reproducible.

## Milestones

**M0 — scaffold and dependencies.** Create the repo structure. Pull and build everything above. Success: headless OpenTTD starts with OpenGFX and loads an empty test map, and `scripts/setup.sh` reproduces the environment. Checkpoint.

**M1 — workload renders in the golden model.** Write a Python CHIP-8 interpreter (a few hundred lines, verify it against c-octo on a couple of standard test ROMs) and a framebuffer viewer. Success: an existing CHIP-8 test ROM runs in your interpreter and draws to the viewer. Then begin progressing toward a raycaster ROM (find one, else scaffold). This leg proves the workload renders, with zero OpenTTD involvement. Checkpoint.

**M2 — one working gate (the foundational primitive).** Using the openttdcoop / zem.fi constructions as reference, get a single logic gate (a NOR or a NOT) implemented as an OpenTTD tile stamp that loads and verifiably computes in headless OpenTTD. Decide and document the construction mechanism here: either (a) write the `.sav` binary directly (research the chunked savegame format), or (b) drive construction via a **GameScript** (Squirrel API) that builds the track/signals/trains when the scenario loads. Option (b) likely dodges the binary format and is the more tractable path, try it first. Success: poke the gate's input, observe the output flip. This is the hardest foundational piece, treat it with care and rule 3. Checkpoint.

**M3 — toolchain spine.** Amaranth frontend describing circuits, a primitive cell library mapping to the M2 gate stamp, yosys synthesis to a netlist of those cells, a place-and-route pass that positions cells and routes signal nets as track, and an emitter that turns the placed design into a loadable OpenTTD scenario (reusing the M2 construction mechanism). It is fine if routing is crude. Checkpoint.

**M4 — THE GATE (de-risking milestone).** A 4-bit ripple-carry adder: define it in Amaranth, synthesise to the cell netlist, place and route, emit the scenario, load it in headless OpenTTD, and verify it adds. Get as far as you can. If you cannot fully close it, build the whole pipeline and isolate the exact blocker (most likely the gate tile geometry or the construction step) in `STUCK.md`. **Stop here and write `STATUS.md` for human review.**

## Out of scope (stub and roadmap only, do NOT attempt)

- The full CHIP-8 / XO-CHIP datapath in HDL.
- Running the raycaster on the train-built machine.
- The OpenTTD engine fork for speed (stripped tick loop, route/pathfinding surgery, uncapping).
- Bayer dithering, grayscale, palette-index colour.
- Trains-as-pixels display.
- Rendering actual DOOM frames.

Leave each of these as a short section in `README.md` under "Roadmap" with a one-line description, so the path is documented but untouched.

## Deliverables at stop

A repo that builds and runs via the scripts, a `README.md` with the architecture and roadmap, a working Python golden model and viewer, as much of the HDL-to-OpenTTD pipeline as you could verify, and a `STATUS.md` plus `STUCK.md` that hand the human a clean map of what works and exactly where the hard problems sit.