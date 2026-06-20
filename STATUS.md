# STATUS

End-of-run status for openttdoom. What works, what is stubbed, and where the hard
problems sit. Plain tone, no em-dashes. The isolated blockers are in STUCK.md.

This run stood up the toolchain spine (M0 to M4) and pushed the 4-bit adder as far as
software verification can take it. The whole pipeline closes in software. The one thing
that does not close is the physical OpenTTD gate, which is the research problem the brief
flagged as hardest, and it is isolated cleanly for the human.

Total test count: 75 passing (`python -m pytest -q`).

## Milestone by milestone

### M0, scaffold and dependencies. DONE, verified.

- Prebuilt OpenTTD 15.3 win64 and OpenGFX 8.0 are pulled by `scripts/setup.sh` into
  `vendor/openttd/`. The binary runs headless: `scripts/run_headless.sh` runs the null
  driver tick loop and exits 0.
- Verified the sim loop actually runs, not just that the process starts: wall-clock scales
  linearly with the tick count, ticks=1 takes about 0.9s (startup) and ticks=100000 takes
  about 17.6s, near 6000 ticks per second. OpenTTD aborts at startup if no base set is
  found, so OpenGFX is confirmed in use.
- Deviation: we use the prebuilt binary, not a CMake source build, because this environment
  has no C or C++ compiler. The source-build steps are a comment in `scripts/setup.sh`.

### M1, workload renders in the golden model. DONE, verified.

- `golden/chip8.py` is a complete CHIP-8 interpreter (all standard opcodes, VF carry/borrow
  written after the op, DXYN sprite XOR with collision plus wrap and clip, the FX family
  including FX0A key wait, FX33 BCD, FX55/65 with I increment, six quirk flags at classic
  defaults). Bad-state paths halt gracefully rather than raising.
- `golden/viewer.py` is headless-first: `save_png` renders the 64x32 buffer to a 1-bit PNG,
  `run_rom` runs a ROM. pygame live view is optional and guarded.
- Cross-checked against the Timendus chip8-test-suite reference ROMs (`vendor/chip8/roms/`).
  The IBM logo, corax+ and flags renders are pinned by exact framebuffer sha256, not by a
  weak pixel-count bound. This was shown to matter: a deliberately inverted 8XY5 borrow flag
  leaves the lit-pixel count unchanged but changes the hash, so the exact assertion catches
  it where a count-only check would not. Renders are in `golden/out/` (committed as proof).
- Deviation: a c-octo cross-check is not possible here (no compiler). The Timendus reference
  ROMs are the substitute, and the corax+ and flags screens show a pass marker on every
  opcode and flag group.
- The raycaster ROM was searched for, not built (per the brief). See `golden/RAYCASTER.md`:
  the realistic candidates are XO-CHIP (Chipenstein 3D, Simple Raycaster), there is no clean
  plain-CHIP-8 monochrome one, and a minimal Octo plan is sketched as a later task.
- Note: the vf_reset quirk is not visible in the vendored corax+/flags framebuffers (the
  Timendus 5-quirks ROM that would show it is not vendored). vf_reset is covered by the unit
  tests `test_8xy1_or_vf_reset` and `test_8xy2_and_vf_reset_off` instead.

### M2, one working gate. PARTIAL. The design is researched and the build mechanism is chosen. The physical gate geometry is the isolated blocker.

- `scenarios/GATE_DESIGN.md` is the design and research note: how a clocked NOR is meant to
  be realised from track, signals (block, two-way, entry/exit/combo presignals) and a clock
  train, why we use single-track train-presence encoding sampled at the clock edge, the
  one-edge latency, and the construction-mechanism decision (GameScript over hand-writing the
  binary savegame, with rationale). Sources are cited.
- `scenarios/gate_model.py` is a Python model of the intended clocked NOR/NOT tile, with
  16 passing tests pinning the NOR and NOT truth tables and the one-edge latency. This proves
  the intended semantics are self consistent. It does NOT prove OpenTTD realises them.
- `scenarios/openttdoom_gs/` is the GameScript that reads the place-and-route data table and
  walks cells, routes, clock, IO and framebuffer using the real GS API. It is an honest
  skeleton: every spot that needs real track and signal coordinates is marked `TODO(human)`,
  and the stamp helpers lay placeholder straights that do NOT compute. No fabricated geometry.
- Blocked: the exact tile-by-tile NOR construction, the GameScript actually running, and the
  deity/company build-context question. See STUCK.md.

### M3, toolchain spine. DONE, verified in software.

- `hdl/` is the Amaranth frontend: a behavioural `Adder4` (the golden reference, simulated
  over all 512 input combos) and `build_adder4_netlist()`, a structural ripple-carry adder
  built from full adders. `hdl/cells.py` has the primitive cells, now unit-tested.
- `synth/netlist.py` is the gate-level netlist contract: the cell library (NOR is the only
  buildable gate, NOT is a one-input NOR), the software "golden hardware" simulator,
  `to_nor()` lowering to the buildable set, and JSON IO. `equivalent()` compares by truth
  table and is port-order independent.
- `synth/synth.py` emits `synth/out/adder4.json` (structural, 82 NOR) and
  `synth/out/adder4_nor.json` (lowered buildable, 92 NOR). A real WASM yosys (amaranth-yosys)
  is reachable and is used as a cross-check that genuinely decomposes a bit-level adder to
  gate cells. The full verilog-to-NOR-liberty yosys techmap needs a complete yosys and is
  parked in `synth/adder4.ys` as `TODO(human)`. See STUCK.md and the deviation below.
- `place_and_route/` places cells on a grid (footprint sized to fan-in so wide NOR inputs get
  distinct tiles), routes nets with a crude negotiated-congestion maze router, emits a
  `Scenario` (JSON plus the `.nut` data table), and checks it: `drc()` catches overlaps,
  shorts, off-map tiles and pin collisions; `scenario_to_netlist()` reconstructs the logic
  from the placed cells and routes; `verify_equivalence()` proves the placement preserved the
  function. Routing is allowed to be crude and unrouted nets are recorded honestly.

### M4, the 4-bit adder end to end. CLOSES IN SOFTWARE. The OpenTTD realisation is blocked on M2.

Running the whole pipeline on the 4-bit ripple-carry adder:

1. Synthesised netlist: 92 NOR cells, buildable-only, computes a+b+cin correctly on all
   512 input combinations.
2. Place and route: all 92 cells placed, 0 DRC violations, 77 of 101 nets physically routed
   (24 unrouted, recorded honestly, see STUCK.md on the router).
3. Reconstruction from the emitted scenario (reading back the placed cells and routes):
   `verify_equivalence` is True and the reconstructed netlist computes a+b+cin on all 512
   combinations.

So the design closes from Amaranth down to a loadable scenario and the logic is preserved at
every step, verified in software. The scenario and GameScript data are emitted
(`scenarios/adder4.scenario.json`, `.nut`, and `scenarios/openttdoom_gs/scenario_data.nut`).
What does not close is the last hop: a GameScript stamping a NOR tile that actually computes
in OpenTTD, because the gate geometry is unsolved. That is the brief's expected outcome for
M4 ("build the whole pipeline and isolate the exact blocker"), and it is isolated in STUCK.md.

## The tricky bits handed to the human (file pointers)

1. The physical OpenTTD NOR gate geometry. `scenarios/GATE_DESIGN.md` (the design),
   `scenarios/openttdoom_gs/main.nut` (the `TODO(human)` markers in `StampCell`). STUCK.md #1.
2. Running and verifying the GameScript in OpenTTD, plus the company build-context.
   `scenarios/openttdoom_gs/readme.txt`, `main.nut::PickCompany`. STUCK.md #2 and #3.
3. The router does not reach 100% on multi-bit adders. `place_and_route/route.py`. STUCK.md #4.
4. The full yosys NOR-liberty techmap. `synth/adder4.ys`. STUCK.md #5.

## Deviations from the brief, all documented

- Prebuilt OpenTTD binary instead of a CMake source build (no compiler here).
- Timendus reference ROMs instead of a c-octo cross-check (no compiler here).
- `amaranth-yosys` and `wasmtime` were pip-installed at runtime for the optional yosys
  cross-check. The verified pipeline does not depend on them; they self-skip if absent.
- yosys and verilator proper are not installed (the structural Python path is the verified
  one). `scripts/setup.sh` documents the oss-cad-suite bundle for a human who wants them.
