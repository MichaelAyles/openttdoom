# openttdoom

A Wolfenstein-3D style raycaster running on a small computer built entirely out of
OpenTTD trains and signals, with the framebuffer drawn as on-map signals.

This run stands up the toolchain spine and pushes toward one de-risking milestone, a
4-bit adder running end to end inside OpenTTD. This is not a working DOOM. It is the
scaffolding a human takes over from. For the per-milestone status and the isolated hard
problems, see STATUS.md and STUCK.md.

## The pipeline

The whole project is one compiler from a circuit description down to an OpenTTD map, with
a software reference model running alongside to keep us honest.

```
  golden model (Python CHIP-8 + viewer)     proves the workload renders, no OpenTTD
        |
        |   (reference only, runs in parallel)
        v
  HDL  ->  netlist  ->  place & route  ->  scenario  ->  OpenTTD substrate
 (hdl/)   (synth/)    (place_and_route/)  (scenarios/)   (trains + signals)
```

Stage by stage:

- **golden/**  A Python CHIP-8 interpreter and a framebuffer viewer. CHIP-8's native
  64x32 monochrome display maps 1:1 onto the signal framebuffer, so this proves the
  workload renders with zero OpenTTD involvement. It is the oracle we check the hardware
  against.
- **hdl/**  An Amaranth (Python) description of the machine and a primitive cell library.
  The HDL frontend emits a `Netlist`.
- **synth/**  Synthesis. A `Netlist` is a set of cells from a tiny library. The only cell
  physically built on the substrate is NOR (it is universal, and NOT is just a one-input
  NOR). `Netlist.to_nor()` lowers a general netlist to the buildable set
  `{NOR, CONST0, CONST1}`, which is what a real yosys techmap to a single-gate library
  would produce. yosys itself is optional here, see "Verified vs stubbed".
- **place_and_route/**  Takes a netlist and produces a `Scenario`: a fully spatial layout
  where every cell has a footprint and a tile position, every net is a routed track path,
  and the primary inputs and outputs are pads at known tiles. Routing is allowed to be
  crude.
- **scenarios/**  The emitter turns a placed `Scenario` into a Squirrel data table
  (`scenario_data.nut`) via `Scenario.to_nut()`. A GameScript reads that table on load and
  stamps the track, signals and trains onto the map. This dodges the binary savegame
  format.
- **OpenTTD substrate.**  Bits are signal states, train presence is the value (train
  present means 1), and gates are track geometry from the openttdcoop and zem.fi logic
  references. A train on a fixed loop is the clock. The design is synchronous and clocked.

### The framebuffer and the signal mapping

The display is 1-bit signals on the map, signals as pixels. A netlist's `ports.outputs`
become output pads, and the framebuffer is a rectangle of those pads. CHIP-8's 64x32
frame becomes a 64x32 grid of signal tiles, one signal per pixel, present or not. A Python
viewer reads the framebuffer back out of the sim for clean frames and for capture and
replay. Colour, grayscale and Bayer dithering are out of scope this run (see Roadmap).

## Build and run

Everything is behind three scripts in `scripts/`. They target Git-Bash / MINGW on Windows,
which is the environment this repo was built and verified in.

1. **Set up the environment.**

   ```
   bash scripts/setup.sh
   ```

   Downloads the prebuilt OpenTTD 15.3 win64 binary into `vendor/openttd/`, places the
   OpenGFX 8.0 base graphics tar into the binary's `baseset/`, and pip-installs the Python
   toolchain (amaranth, numpy, pillow, pytest, pygame). It is idempotent: re-running skips
   downloads that already landed. yosys and verilator are optional and are not installed
   here, the script documents the oss-cad-suite bundle for a human who wants them.

2. **Run the headless smoke test.**

   ```
   bash scripts/run_headless.sh [TICKS]
   ```

   Runs the binary with null video, sound and music drivers for `TICKS` ticks (default
   20000), then exits. This proves the binary launches, loads OpenGFX and spins the tick
   loop. Note the GUI-subsystem caveat: the Windows release binary does not pipe stdout
   back to the shell, so you will not see log lines. Success is shown by exit code 0 and by
   the wall-clock time scaling with the tick count, at roughly 6000 ticks per second on
   this machine.

3. **Build the toolchain end to end.**

   ```
   bash scripts/build.sh
   ```

   Runs synth, then place-and-route plus the emitter on the 4-bit adder, copies the
   generated `.nut` into the GameScript at `scenarios/openttdoom_gs/scenario_data.nut`, and
   runs the pytest suites. It prints the artifact paths at the end.

## Verified vs stubbed

Verified in this environment:

- The prebuilt OpenTTD 15.3 binary runs headless. The smoke test exits 0, and the
  wall-clock time scales with the tick count (20000 ticks in about 3 seconds, near 6000
  ticks per second).
- OpenGFX 8.0 is in place in `baseset/`, which is what lets the binary start.
- The toolchain contracts are committed and import cleanly: the gate-level `Netlist` in
  `synth/netlist.py` and the placed `Scenario` schema in `place_and_route/scenario.py`.

Stubbed or optional, not relied on here:

- **yosys and verilator are not installed.** The synth flow uses the self-contained Python
  NOR lowering (`Netlist.to_nor`) instead of a real yosys techmap, so the verified pipeline
  does not depend on them. A human can add them via the oss-cad-suite bundle. See
  `scripts/setup.sh`.
- **Building OpenTTD from source is not done here**, because this environment has no C or
  C++ compiler. We use the prebuilt binary. The CMake build steps a human would run are
  noted as a comment in `scripts/setup.sh`.
- The exact end-to-end state of the gate stamp and the adder (M2 to M4) is tracked in
  STATUS.md, with the isolated blockers in STUCK.md. Those are the files to read for what
  actually closed versus what is handed to the human.

## Roadmap / Out of scope

These are documented so the path is clear, but were not attempted this run.

- **Full CHIP-8 / XO-CHIP datapath in HDL.** Only the toolchain spine and the adder are in
  scope, not the whole VM described in Amaranth.
- **Running the raycaster on the train-built machine.** The raycaster ROM is a workload for
  the golden model only this run, not for the OpenTTD substrate.
- **OpenTTD engine fork for speed.** The stripped tick loop, route and pathfinding surgery
  and uncapped speed that make this run fast are human-led and out of scope.
- **Bayer dithering, grayscale and palette-index colour.** The framebuffer is 1-bit only
  this run, no colour and no dithering.
- **Trains-as-pixels display.** The framebuffer is signals as pixels (P0). Using trains
  themselves as pixels is a later stretch.
- **Rendering actual DOOM frames.** We use DOOM only for the look and palette as reference,
  not to run it or to render real DOOM frames on the substrate.
