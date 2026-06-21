# STATUS

End-of-run status for openttdoom. What works, what is stubbed, and where the hard
problems sit. Plain tone, no em-dashes. The isolated blockers are in STUCK.md.

This run stood up the toolchain spine (M0 to M4) and pushed the 4-bit adder as far as
software verification can take it. The whole pipeline closes in software, with the adder
fully placed AND fully routed. The one thing that does not close is the physical OpenTTD
gate, which is the research problem the brief flagged as hardest, and it is isolated cleanly
for the human.

Two of the four originally-isolated blockers were then closed (see the history at the bottom):
routing now reaches 100 percent via perpendicular bridge crossings, and a full yosys
(oss-cad-suite) now runs the proper verilog to NOR synthesis, verified equivalent to the
Python flow. The remaining blockers are the physical gate geometry and the GameScript runtime.

Total test count: 80 passing (`python -m pytest -q`).

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

### M2, one working gate plus composition, a clock train, and live re-evaluation. DONE and verified in game for NOT, 2-input NOR, a 2-gate OR chain, a clock train, and live same-tile re-evaluation. Full clock-synchronised sampling is not yet reliable.

- `scenarios/GATE_DESIGN.md` is the design and research note: how a clocked NOR is meant to
  be realised from track, signals (block, two-way, entry/exit/combo presignals) and a clock
  train, why we use single-track train-presence encoding sampled at the clock edge, the
  one-edge latency, and the construction-mechanism decision (GameScript over hand-writing the
  binary savegame, with rationale). Sources are cited.
- `scenarios/gate_model.py` is a Python model of the intended clocked NOR/NOT tile, with
  16 passing tests pinning the NOR and NOT truth tables and the one-edge latency. This proves
  the intended semantics are self consistent. It does NOT prove OpenTTD realises them.
- `scenarios/openttdoom_gs/` is the GameScript that reads the place-and-route data table and
  walks cells, routes and bridges using the real GS API. The stamp helpers lay placeholder
  track (one straight per pin, track along each route, a bridge at each crossing), which is
  visible structure but does NOT compute. The computing NOR geometry is still `TODO(human)`.
- NOW PROVEN, TWO WAYS, the placed-and-routed design appears as real rail in OpenTTD:
  1. GameScript build: the GS runs in OpenTTD and stamps the design as rail and bridges at
     runtime. The construction mechanism and the deity/company context are solved: a dedicated
     server (`-D`) builds headlessly, a company is made with the RCON command `start_ai` that
     the GS waits for, and the GS maxes its loan to afford it. Automated in `tools/ottd_render.py`,
     driven via the admin port (`tools/ottd_admin.py`). Robust but slow (a big design takes
     minutes of in-game build time).
  2. Direct save writer (`tools/sav_writer.py`): writes the design straight into an
     uncompressed OTTN savegame by editing the map tile arrays in place (the rail-tile encoding
     reverse-engineered from the OpenTTD 15.3 source: type/MAPT, owner/MAPO, track bits/MAP5,
     rail type/MAP8, per rail_map.h MakeRailNormal). This is INSTANT (the full 4-bit adder,
     40k tiles, in ~0.3s), needs no company/money/build, and can flatten the map to a plain
     canvas of any size. Screenshots of the 1-bit, 2-bit and 4-bit adders are in `out_screens/`.
  What remains blocked is only the exact tile-by-tile NOR geometry that makes a stamped cell
  COMPUTE (the layouts above are visible structure, not working logic). See STUCK.md #1.
- NOW SOLVED AND VERIFIED IN GAME: a single computing gate. `scenarios/norgate_gs/` builds a
  NOT (one-input NOR) and a 2-input NOR from OpenTTD track + a block signal and PROVES they
  compute by poking the inputs and watching the output flip, observed from the GameScript via
  `GSVehicle.GetLocation`. Verified 2-input NOR truth table: 00->1, 01->0, 10->0, 11->0 (all
  four combinations on one structure); NOT: A=0->1, A=1->0 (the same physical gate poked twice).
  The bit is train-presence on a block; a block signal is red iff its block is occupied, so a
  reader train passes the signal iff every input is absent, which is NOR. The output is read by
  where the reader ends up. Two coordinate-level facts were the crux: `GSRail.BuildSignal(tile,
  front)` permits travel FROM front INTO tile (so an eastbound reader needs front = SIGX-1, the
  OPPOSITE of the naive guess), and the protected block must be a through block (a second
  terminating signal), because a normal signal in front of a dead-end block stays red. The build
  area is demolished+LevelTiles'd first so a random map's lakes do not truncate the rail. Exact
  geometry is in `scenarios/GATE_DESIGN.md` (the "SOLVED AND VERIFIED" section) and
  `scenarios/norgate_gs/readme.txt`.
- INDEPENDENTLY RE-VERIFIED (orchestrator). The GameScript GSLog relay to the admin port turned
  out NOT to be reliable here, so the original GSLog evidence could not be reproduced through that
  channel. The 2-input NOR was therefore re-run from scratch through a different, robust readout:
  the gate encodes the four raw reader-train x positions into the COMPANY NAME, read back via
  `rcon companies` (`scenarios/norgate_gs/main_verify_byname.nut`). Fresh run returned
  `NORFX sig46 51 45 39 39`: reader passed the signal (x=51 > 46) only for inputs 00, and was
  held (x <= 46) for 01/10/11. Applying NOR(a,b) = (reader passed) to the RAW positions gives
  1,0,0,0 = NOR, judged by the orchestrator, not by the GameScript. So the gate genuinely
  computes, confirmed independently of the agent's own logging and pass/fail computation.
  NOW ALSO VERIFIED IN GAME: gate COMPOSITION, a TWO-GATE CHAIN computing
  OR(a,b) = NOT(NOR(a,b)). `scenarios/norchain_gs/` builds gate 1 (a 2-input NOR of primary
  inputs a,b) feeding gate 2 (a NOT, a one-input NOR), so gate2 = NOT(NOR(a,b)) = OR. Gate 1's
  reader, when it PASSES (output 1, both inputs absent), is frozen on a coupling tile CPLX that
  is joined by a signal-free spur into gate 2's input block, so "gate1 output = 1" physically
  parks a train in gate 2's input block; when gate 1 is held (output 0) nothing reaches CPLX.
  Gate 2's reader then passes iff its input block is empty iff gate 1 did not pass. Verified by a
  fresh dedicated-server run, read via the company name (`rcon companies`), encoding the four
  gate-2 reader final x: readout `OR s40 39 41 41 41` (SIG2X=40; reader x>40 == passed == OR 1).
  Judged from the RAW positions: 00->g2=39<=40 (OR 0), 01->41, 10->41, 11->41 (all >40, OR 1),
  giving 0,1,1,1 = OR(a,b), exactly. The per-case live names also showed gate 1 working inside
  the chain: gate1 reader parked at CPLX=42 only for inputs 00 and was held at x=35 for
  01/10/11, i.e. NOR = 1,0,0,0. So both gates compute and gate 1's output drives gate 2's input.
  Two engineering facts were the crux (both isolated empirically, see norchain_gs/main_diag3.nut):
  a dead-end "hold" signal does NOT cleanly park the passing reader (it gets held a tile early),
  so the reader is parked by freezing it (StartStopVehicle) the moment its x reaches CPLX; and
  tearing trains down between cases on the coupled junction hangs the script (a restarted reader
  loops at the spur), so each of the four cases is built as an INDEPENDENT chain copy at its own
  band of rows, with no teardown. Also confirmed: long company names silently fail to set (a
  length limit), so the readout is kept short.
- NOW ALSO VERIFIED IN GAME: a clock train and live re-evaluation (`scenarios/clockgate_gs/`).
  (1) Clock train: a single train circulates a small closed rail loop with a measured, stable,
  repeating lap period (about 26 to 27 sample-intervals over six laps, the +/-1 is the discrete
  poll alias), proven from the train's tile positions cycling, not from any GameScript logic
  (`main_clock.nut`). (2) Live re-evaluation on the SAME tiles: one NOT gate is built once, then
  with everything still running the input is poked live and the reader re-run, with NO rebuild.
  Independently re-verified by the orchestrator via the company name: `REEVAL s46 52 45 52` (sig
  at x=46) means read A input absent reader x=52 (passed, output 1), read B input poked onto the
  same gate x=45 (held, output 0), read C input removed x=52 (passed, output 1). The same gate's
  output followed the live input 1,0,1 (`main_reeval.nut`).
  NOT VERIFIED: full clock-synchronised sampling (`main_sync.nut`). The build agent saw the gate
  output track a driven input schedule (001100 -> 110011 = NOT per edge) in two runs, but
  independent re-verification could NOT reproduce it (zero clock-released edges in three tries, the
  clock train stalled). The release is GameScript-mediated, not a pure track-signal interlock, and
  there is no physical output register, so this is unreliable and is documented as the remaining
  hard piece in STUCK.md, not claimed as done.
  STILL OPEN: tying the verified clock and re-evaluation together into a reliable synchronous gate
  (a pure clock-driven release interlock and a one-edge output register), the one-edge register
  latency, the framebuffer readout, and folding the geometry into the place-and-route emitter.
  The chain and these primitives now rest on working, verified pieces rather than unknowns.
- ATTEMPTED, NOT ACHIEVED: a PURE track-signal clock interlock (`scenarios/syncgate_gs/`). A
  follow-on run tried to replace the GameScript-mediated clock release with a real interlock (the
  clock train's block occupancy physically releasing the reader, plus an output register). It did
  not close, and the blocker is now precisely characterised: in OpenTTD 15.3, reading the clock
  block's occupancy by signals couples the RESERVATION graph, so a circulating reader makes the
  clock's loop tile unreservable and the clock stalls. Three different read mechanisms (block-merge,
  presignals, PBS) all failed the same way. A more-reliable self-sustaining clock (one-way block
  signals round the loop) came out of it, with a stable steady-state period, though its launch is
  still flaky (independent verification: 3 of 5 fresh runs, the two failures at launch). The output
  register was not built (it depends on the interlock). The exact blocker and three untried
  workarounds (clock block off the mandatory loop path, multiple clock trains, a strictly
  one-directional detector) are in STUCK.md for the human. This is an honest negative result: the
  pure interlock is a real OpenTTD reservation-coupling obstacle, not a tuning miss.

### M3, toolchain spine. DONE, verified in software.

- `hdl/` is the Amaranth frontend: a behavioural `Adder4` (the golden reference, simulated
  over all 512 input combos) and `build_adder4_netlist()`, a structural ripple-carry adder
  built from full adders. `hdl/cells.py` has the primitive cells, now unit-tested.
- `synth/netlist.py` is the gate-level netlist contract: the cell library (NOR is the only
  buildable gate, NOT is a one-input NOR), the software "golden hardware" simulator,
  `to_nor()` lowering to the buildable set, and JSON IO. `equivalent()` compares by truth
  table and is port-order independent.
- `synth/synth.py` emits `synth/out/adder4.json` (structural, 82 NOR) and
  `synth/out/adder4_nor.json` (lowered buildable, 92 NOR). The proper full yosys path now
  works: with a complete yosys (oss-cad-suite), `synth/yosys_synth.py` runs the real verilog
  to techmap to NOR flow (`synth/adder4.ys`) and produces a 62-cell NOR netlist that adds over
  all 512 combos and is `equivalent()` to the Python flow (yosys abc is tighter, 62 vs 92
  cells). `synth/test_yosys.py` checks this and skips cleanly when yosys is absent. The Python
  `to_nor()` lowering remains the tool-free verified default.
- `place_and_route/` places cells on a grid (footprint sized to fan-in so wide NOR inputs get
  distinct tiles), then routes every net with a deterministic, complete channel router
  (`channel_route.py`): each net gets a unique horizontal trunk row and unique-column vertical
  risers, and where two nets must cross they do so as a perpendicular BRIDGE (one carried over
  the other), which is how OpenTTD crosses signals. It emits a `Scenario` (JSON plus the
  `.nut` data table) and checks it: `drc()` catches overlaps, off-map tiles, pin collisions,
  and any non-bridge short (a same-orientation overlap can never be laundered as a bridge);
  `scenario_to_netlist()` reconstructs the logic from the placed cells and routes;
  `verify_equivalence()` proves the placement preserved the function. The 1, 2 and 4-bit
  adders now route to 100 percent with zero DRC violations.

### M4, the 4-bit adder end to end. CLOSES IN SOFTWARE. The OpenTTD realisation is blocked on M2.

Running the whole pipeline on the 4-bit ripple-carry adder:

1. Synthesised netlist: 92 NOR cells, buildable-only, computes a+b+cin correctly on all
   512 input combinations. (A full yosys produces an equivalent 62-cell version.)
2. Place and route: all 92 cells placed and all 101 nets routed (100 percent), 0 DRC
   violations, on a 1024x256 map, using 1958 perpendicular bridge crossings.
3. Reconstruction from the emitted scenario (reading back the placed cells and routes):
   `verify_equivalence(require_routed=True)` is True and the reconstructed netlist computes
   a+b+cin on all 512 combinations.

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
3. The GameScript bridge construction detail (bridge type, ramp/head tiles, one-way signals).
   The crossings are computed and flow through the data; building them in game needs
   calibration. `scenarios/openttdoom_gs/main.nut::LayBridge`. STUCK.md #4.

Resolved this run (were blockers, now closed): complete routing via bridges, and the proper
full-yosys NOR synthesis. See the history section below.

## Deviations from the brief, all documented

- Prebuilt OpenTTD binary instead of a CMake source build (no compiler here).
- Timendus reference ROMs instead of a c-octo cross-check (no compiler here).
- A full yosys and verilator (oss-cad-suite) were installed outside the repo tree and are now
  used by the optional yosys path. They are kept out of `vendor/` on purpose (the bundle is
  ~2 GB and this tree may be cloud-synced); `synth/yosys_synth.py` auto-detects them and the
  whole flow skips cleanly when they are absent. The tool-free Python path stays the default.
  `scripts/setup.sh` documents the install.

## History, extensions after the M4 review gate

The brief's stop point was the M4 gate, with four blockers isolated. Two were then closed:

- Complete routing. The maze router topped out at 77 of 101 nets on the 4-bit adder. The cause
  was topological, not a weak heuristic: a 4-bit adder netlist is not planar, so some wire
  crossings are unavoidable, and a tile-disjoint (no-crossing) router can never reach 100
  percent. OpenTTD crosses tracks with bridges, so the router was replaced with a deterministic
  channel router (`place_and_route/channel_route.py`) that crosses nets as perpendicular
  bridges. All adders now route to 100 percent, DRC clean, logic preserved. The bridges flow
  through to the GameScript (`main.nut::LayBridge`).
- Proper yosys synthesis. A full yosys (oss-cad-suite) was installed, so `synth/adder4.ys`
  now runs for real (`synth/yosys_synth.py`): verilog to techmap to NOR, giving a 62-cell NOR
  netlist equivalent to the Python flow. verilator (5.049) is available too.

Still open after these: the physical gate geometry (STUCK.md #1), the GameScript runtime and
company context (STUCK.md #2, #3), and the in-game bridge construction detail (STUCK.md #4).
