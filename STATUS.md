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

Total test count: 267 passing (`python -m pytest -q`), of which 20 are the M5 accumulator-CPU
suite (`hdl/test_cpu.py`). (The non-CPU count grew past the 225 noted earlier as parallel tracks
landed; the M5 work added the 20 CPU tests and left every other test green.)

## Milestone by milestone

### M0, scaffold and dependencies. DONE, verified.

- Prebuilt OpenTTD 15.3 win64 and OpenGFX 8.0 are pulled by `scripts/setup.sh` into
  `vendor/openttd/`. The binary runs headless: `scripts/run_headless.sh` runs the null
  driver tick loop and exits 0.
- Verified the sim loop actually runs, not just that the process starts: wall-clock scales
  linearly with the tick count, ticks=1 takes about 0.9s (startup) and ticks=100000 takes
  about 17.6s, near 6000 ticks per second. OpenTTD aborts at startup if no base set is
  found, so OpenGFX is confirmed in use.
- Note on the binary: M0 used the prebuilt binary for convenience, but a source build IS
  possible here and is now verified. The box has MSVC 2022 (Visual Studio Community, cl.exe
  19.43, C++20); it was just not on the Git-Bash PATH, it loads via `vcvars64.bat`. OpenTTD
  15.3 was built from source (MSVC + vcpkg + CMake, with `CMAKE_POLICY_VERSION_MINIMUM=3.5`
  kept via `VCPKG_KEEP_ENV_VARS` so the old `lzo` dep configures under CMake 4.0), and the
  self-built binary passes the same M0 headless timing test. The earlier "no compiler" claim
  was a false negative from a PATH-only check. Build steps are in `scripts/setup.sh`.
- Speed fork, STARTED and verified. With the source build in hand, a first fork gates the per-tick
  map housekeeping useless on a logic map (the cosmetic tile loop `RunTileLoop`, and the
  town/tree/industry/station `OnTick` handlers) behind a runtime flag `OTTDOOM_LOGIC_MAP=1`, keeping
  `CallVehicleTicks` and all signal/pathfinding intact. Measured ~3x on a bare 256x256 map (about
  4600 to 14000 ticks/sec), independently re-measured at 3.05x with a control (the flag on a binary
  WITHOUT the fork code changes nothing, so the speedup is the source strips, not the env var). The
  fork is `docs/speed_fork.md` plus `docs/speed_fork.patch` (the source lives in the OpenTTD tree
  outside the repo). Honest scope: the 3x is fixed housekeeping removed on a bare map; it shrinks
  toward 1x as trains scale, so the per-train pathfinding hot path is the next, deeper lever.
  DEEPENED (per-train cut): on a deliberately train-heavy map (~150 single-train PBS loops, built by
  the `benchmarks/loopbench_ai/` NoAI script), the per-train post-tick bookkeeping that is dead weight
  on a logic train (cargo aging, the sound/motion counter, and smoke/steam effect vehicles) was also
  gated by the flag. Measured 1.033x (smoke off) to 1.067x (smoke on) on the train-heavy map, 3 runs
  each. Modest BY DESIGN: the vehicle's own `Tick` (movement, signal reservation, the YAPF path call)
  was left fully intact, so the remaining per-train floor is the pathfinding, which is the risky lever
  and was deliberately not touched. Correctness PROVEN, not assumed: 50000 deterministic ticks under
  the baseline vs cut binary produce exit saves that differ in exactly 4 bytes per train, all the
  cosmetic `motion_counter`, every movement field byte-identical, and a 500000-tick run exits 0 with no
  desync. So the cut is faster AND movement-neutral. Full stack vs stock on a cosmetic map: ~1.225x.

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

### M2, computing gates plus a clocked machine's primitives. DONE and verified in game for NOT, 2-input NOR, a 2-gate OR chain, a clock train, live same-tile re-evaluation, and a RELIABLE clock-synchronised NOT gate (8/8 fresh runs). The pure hardware interlock and a one-edge output register remain.

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
  NOW VERIFIED RELIABLE: a clock-SYNCHRONISED NOT gate (`main_clocked.nut`). A clock train circulates
  a one-way block-signalled loop; at each of 6 clock edges the GameScript blocks until the clock train
  crosses a fixed loop phase (a real per-edge clock wait), drives a fixed input schedule 0,1,1,0,1,0,
  dispatches a fresh reader, and derives the output bit from the RAW reader position. Output =
  1,0,0,1,0,1 = NOT(schedule), readout `CG 100101`, reproduced in 8 of 8 independent fresh
  dedicated-server runs (an adversarial verifier 5/5 and the orchestrator a further 3/3), per-edge
  raw x identical each run (51 on input-absent edges, 45 on input-present). This fixed the prior
  `main_sync.nut` that reproduced 0/3. The reliability fixes: short readouts (the ~31-char company
  name limit silently froze a long name and masqueraded as a stall), a confirmed-circulating single
  clock train before building, draining each reader to the depot per edge, and a try/catch + re-entry
  guard. Honest scope: this is GS-MEDIATED clock-synchronised sampling (the GS is in the per-edge
  timing path, gated by the clock train's position) and it is combinational NOT sampled per edge
  (output[k] = NOT(input[k]), no register latency).
  NOW ALSO DEMONSTRATED: a CLOCK-STEPPED FIBONACCI READOUT on the proven clocked mechanism
  (`scenarios/clockgate_gs/main_fib.nut`, info_fib.nut, readme_fib.txt, run_fib.sh; installed as the
  `fibgate` GS). A fork of main_clocked.nut: the SAME self-sustaining one-way-block-signalled clock
  loop and the SAME per-edge WaitClockEdge, but with a BANK of 4 parallel block-signal NOR/NOT gate
  lanes (one per output bit) gated by each clock edge. At each of 7 clock edges the GS presents a
  successive Fibonacci term 1,1,2,3,5,8,13 to the bank (lane out = NOT(input present); to make lane i
  output bit b the GS sets that lane's input present iff b==0), then reads all 4 lanes back and decodes
  the value from the RAW reader x (out = x > GSIGX), never from the term list in Squirrel. Readout via
  the SHORT company name: per edge `e<k> v<val> b<bits> p<wait>`, final `F 1 1 2 3 5 8 13`. VERIFIED by
  running fresh dedicated-server passes: edges 0-4 (values 1,1,2,3,5) read correctly in EVERY pass that
  launched the clock, and the COMPLETE sequence `F 1 1 2 3 5 8 13` reproduced in multiple fresh passes
  (batch 3: runs 2,5,6; batch 4: run 4), judged from the raw per-edge positions. HONEST SCOPE: this is
  per-edge RE-PRESENTATION of the terms on the proven clock (the value is freshly presented and computed
  by the gates each edge), NOT a self-feeding hardware register Fibonacci (next = a+b held in track and
  fed back), which needs the physical one-edge OUTPUT REGISTER (the open syncgate item below). RELIABILITY
  caveat, honest: the clock LAUNCH is the documented flaky step (some fresh-server passes CKFAIL when the
  single clock train fails to leave its depot), and the per-edge input CHOREOGRAPHY for the high-value
  terms (8,13, the MSB lane going input-absent) is the same train-dispatch fragility documented for SC2:
  some passes read `F 1 1 2 3 5 0 5` when the MSB lane's input train does not clear in time. A
  dispatch-hardening pass (lane-build self-heal, persistent reader egress, ReverseVehicle + verified
  tap-clear on input removal) reduced but did not fully eliminate these races. Portrait artifacts:
  the 4-bit adder stamped as real rail (`out_screens/portrait_adder4_mini.png`, `_closeup.png`) and the
  fibgate layout on the real map (`out_screens/fibgate_layout_closeup.png`: the clock loop + 4 gate lanes).
  STILL OPEN: a PURE track-signal release interlock with no GS in the timing path (blocked by an
  OpenTTD reservation-coupling, see the syncgate attempt below) and a physical one-edge OUTPUT REGISTER
  for true edge-N = f(edge N-1) latency; then the framebuffer readout and folding the geometry into the
  place-and-route emitter. These rest on working, verified pieces rather than unknowns.
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
- KEYSTONE, the toolchain EMITS a computing cell (SC1, `scenarios/computecell_gs/`,
  `tools/run_sc1.py`). A one-cell NOR2 netlist runs through the real place_and_route (place + emit),
  and the GameScript stamps the verified computing-NOR geometry AT THE PLACED position: every gate
  tile is `cell.x`/`cell.y` plus a fixed footprint offset, no hand-coded map coordinate (`place.py`
  footprint frozen to CELL_W=14, CELL_H=3). It computes: readout `SC1 s19 24 18 12 12` gives 1,0,0,0
  = NOR, judged externally from the raw reader positions (x > SIGX), never from the inputs in
  Squirrel. Verified: the orchestrator got 4/4 identical fresh runs, the build agent 5/5, an
  adversarial verifier 4/5 (one run a polling-timing flake, not a logic fault), and the source was
  audited to confirm emitted-from-placement. This is the first time the pipeline produces WORKING
  hardware in OpenTTD, not just visible structure.
  NOW ALSO ACHIEVED (SC2, mechanism verified, reliability flaky under CPU contention): wiring TWO
  emitted cells together. A 2-cell OR = NOT(NOR(a,b)) netlist
  (gate1 NOR2(a,b) -> net w, gate2 NOT(w) -> y) runs through the real place_and_route (places +
  routes 4/4), the GS stamps gate1 at its placed origin and CO-LOCATES gate2 (the consumer) three
  rows below it with its input tap column derived from gate1's frozen output-rest column, and the
  inter-cell bit transfers PHYSICALLY over a short pure-vertical no-signal track spur (the proven
  norchain coupling): gate1's passing reader, frozen on its rest tile, occupies gate2's input block,
  so gate2 = NOT(gate1) = OR. The link is verified to be the EMITTED routed net w (g0.output.net ==
  g1.input.net), and every coordinate derives from the placed gate1 origin (moving gate1 in the
  placement moves the whole chain). Readout `OR s24 23 29 29 29` (g2sigx=24; x>24 => OR 1): judged
  from the RAW gate2 reader x, 23->0, 29->1, 29->1, 29->1 = 0,1,1,1 = OR(a,b), no OR computed in
  Squirrel. The fix is path (A) (placement-constrained chain layout, the consumer co-located directly
  below its driver via a short pure-vertical spur), which made the block-merge that the earlier long
  L-coupling could not. Two crux facts: gate1's east depot must be FAR past the rest tile (grest+5)
  so the passing reader stays on open track (in the block) when frozen, not rolled into a near depot
  (a near depot gave `OR s24 29 29 29 29`, the merge reading empty); and reader launches need a
  BuildVehicle retry plus a persistent depot-exit nudge (BuildAndLaunch) to kill a stochastic
  whole-run launch stall (`OR s24 17 17 17 17`, every reader stuck in its west depot) that the
  parallel speed-fork's openttd_fast.exe CPU contention made more frequent. VERIFIED that the
  MECHANISM is real (both agents confirmed, source-audited: emitted-from-placement, the coupling is
  physical track, the output is read only from raw gate2 reader x, no OR in Squirrel) and that it
  reproduces `OR s24 23 29 29 29` = 0,1,1,1. RELIABILITY is the honest caveat: the build agent got
  5/5 after hardening, but INDEPENDENT verification got 3/5, and a CLEAN orchestrator re-verify with no
  CPU contention (the speed-fork track had finished) ALSO got 3/5: runs 1,3,5 gave `OR s24 23 29 29 29`
  = 0,1,1,1, run 2 gave `OR s24 23 23 29 29` = 0,0,1,1 (case 01's input b did not park, so gate1 wrongly
  saw an empty input), run 4 produced no readout (a launch stall). So the earlier "just contention"
  read was WRONG: the flakiness is a GENUINE per-case train-dispatch fragility (an input train not
  parking, a reader not launching), not the parallel speed fork. The MECHANISM is correct, every clean
  run gives exactly 0,1,1,1, but the per-case choreography (build, park each input, launch each reader,
  across 4 cases x 2 gates) was only ~3/5 reliable. A dispatch-hardening pass (confirm-then-proceed
  polling instead of fixed Sleeps; ParkInputConfirmed rebuild-until-on-tap; BuildAndLaunch egress
  confirmation; yielding inside Prepare's ~1000-tile demolish so the command queue stops starving
  launches) raised it but did NOT make it solid: across three independent 5-run samples of the hardened
  gate the harden agent got 5/5, an independent verifier 4/5, and the orchestrator 3/5, so ~12/15 = 80%.
  The residual failures are the SAME two races (an input train not catching on its tap, a reader not
  leaving its depot). ROOT CAUSE, now understood: the input bit is set by catching a MOVING train on a
  junction tap tile (a through-tile the train will not stop on by itself) and the reader is launched
  from a depot, both inherently racy, so retry-tuning only softens them. At ~80% per 2-gate circuit this
  does NOT scale (an emitted adder is ~10-20 cells, 0.8^N collapses). The real fix is DETERMINISTIC
  placement by construction: an input train that RESTS on its tap by a holding signal/stub rather than
  being caught mid-motion, and a reader that is gated to leave deterministically. That mechanism-level
  fix, not more retry-tuning, is the open item and the enabler for SC3 (the emitted adder). Run with
  `tools/run_or.py`; see scenarios/computecell_gs/ (RunCopyOR/ParkInputConfirmed/BuildAndLaunch) and
  readme.txt Stage 2.

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

### M3 extension, SEQUENTIAL synthesis. DONE, verified in software.

The toolchain reached combinational logic only; it now also lowers CLOCKED designs. Built on
the register cell (the `DFF` in `synth/netlist.py`, lowered to an all-NOR master-slave latch by
`to_nor()`), the synthesis spine now has a full Amaranth `m.d.sync` to register-netlist path.

- `hdl/sequential.py` is the sequential counterpart of `hdl/adder.py`. Two worked examples, each
  in the adder's three views: a 1-bit TOGGLE flip-flop and an n-bit up COUNTER with enable.
  View 1 is behavioural Amaranth using `m.d.sync` (`Toggle`, `Counter`), simulated with
  `amaranth.sim` over several clock cycles. View 2 is a tool-free STRUCTURAL gate + DFF netlist
  (`build_toggle_ff`, `build_counter`) built from `NetlistBuilder` using the new `dff_into()`
  for the state-feedback registers (the counter's incrementer reads the register outputs and
  feeds the register inputs, a real state-to-logic-to-state loop). View 3 is a plain Python
  reference (`toggle_reference`, `counter_reference`), the ground truth, mirroring
  `alu8_reference`. The structural counter matches the reference exactly for 2, 3 and 4 bits,
  and both lower to the buildable `{NOR, CONST0, CONST1}` set plus the latch feedback.
- `synth/netlist.py` gained the SEQUENTIAL EQUIVALENCE check the brief asked for. `equivalent()`
  compares COMBINATIONAL netlists by their full truth table; a clocked netlist has no static
  truth table (it is a function of the input history), so `sequential_equivalent(a, b, trace)`
  drives both netlists with the identical input trace one full clock cycle per entry and asserts
  their output traces (and, with `state_nets`, their internal register-state traces) are equal
  cycle for cycle. `simulate_trace()` is the underlying stepper (the sequential analogue of
  `truth_table()`), and `NetlistBuilder.dff_into()` drives a register output net reserved up
  front so feedback loops can be wired (also reused by the place-and-route keep-register lowering).
- `synth/synth_seq.py` is the entry point (like `synth/synth.py`): it writes the structural and
  buildable-lowered toggle and counter netlists to `synth/out/`. When a full yosys is installed
  it ALSO runs the proper verilog to `$_DFF_P_` + NOR flow (`synth/yosys_seq.py`): yosys emits a
  synchronous-reset enabled flop for the `m.d.sync` register, `dfflegalize -cell $_DFF_P_ 0`
  lowers it to a PLAIN positive-edge D flip-flop (enable and reset pushed into the data logic),
  which imports straight onto the `DFF` cell, and `abc -g NOR -dff -keepff` maps the rest to NOR.
  Verified here: the yosys 2-bit counter (2 DFF + 13 NOR) computes the reference up-count exactly.
- Honest note on the lowering. The all-NOR master-slave latch has no async reset (the train
  substrate has none either), so a SELF-FEEDBACK register such as this counter or the toggle
  powers on at a physically arbitrary state. With no external data path to flush it, the
  behavioural-DFF form and its `to_nor()` all-NOR form run the SAME transition function but from
  a CONSTANT state offset (the counter's lowering is consistently +1, proven across a long random
  trace), rather than matching from cycle 0. For registers WITH an external data path (the DFF,
  the shift register) `sequential_equivalent` matches exactly after the pipeline is flushed
  (`skip_cycles` = register depth). The yosys flop, which has a real synchronous reset to 0,
  powers on at 0 and matches the reference with no offset. This is documented in
  `NetlistBuilder.dff_nor` and pinned by the tests, not papered over.
- Tests: `hdl/test_sequential.py` (16) covers behavioural-vs-reference, structural-vs-reference,
  the buildable lowering and its constant-offset transition equivalence, the worked example end
  to end, and the optional yosys cross-check; `synth/test_register.py` gained 6 contract tests for
  `simulate_trace` / `sequential_equivalent` / `dff_into`. All green.

SEQUENTIAL PLACE-AND-ROUTE (registers + a clock-distribution net), DONE in software. The placer
and router were extended from combinational-only to CLOCKED designs, so the same sequential
netlists above flow all the way to a placed, routed scenario:

- `place_and_route/place.py` places a DFF as a REGISTER TILE (`REG_W`x`REG_H`, bigger than a NOR)
  with the clock on its OWN west-edge pin (`PlacedCell.clock`), off the data pins, so the clock
  never shorts onto data. The level pass treats a register as a TIMING BOUNDARY (a cell reading a
  register's Q does not chain its column through the register), so a sequential netlist with
  feedback through a register (the toggle, the counter) is placeable instead of looking like a
  combinational loop. A purely combinational loop still raises.
- `place_and_route/channel_route.py` routes the CLOCK net like any other net: one source fans out
  to every register's clock pin via the net's unique trunk row (the clock SPINE) plus a riser onto
  each clock pin, crossing other nets only as legal perpendicular bridges. So the clock reaches
  every register tile with no clock-specific routing rule. Honest simplification: this is a single
  trunk-row spine, not a buffered H-tree, which is sufficient for the train-loop clock model.
- `synth/netlist.py` gained `to_nor(keep_registers=True)` (lower the logic to NOR but keep each
  register as one placeable DFF tile) and `combinational_cone()` (cut the registers so the
  next-state/output logic has a static truth table for `equivalent()`). `scenario.py`,
  `check.py` and `emit.py` carry the clock pin/reset through placement, JSON, the `.nut`, the DRC
  (clock pin is a legal landing tile, the clock route must reach every register), reconstruction
  and map sizing, all backward compatible (old JSON without the fields still loads).
- Verified end to end on the toggle flip-flop and the up-counter FROM THE SYNTH WORK plus a
  4-stage shift register: each PLACES with one register tile per DFF, ROUTES to 100 percent of
  nets with 0 DRC violations, the clock reaches EVERY register, and the emitted Scenario/.nut
  RECONSTRUCTS to a netlist that steps cycle-for-cycle identically under SeqSim AND whose
  combinational cone is `equivalent()` to the source cone. The 3-bit counter is saved as
  `scenarios/counter3.scenario.json`/`.nut` (37 cells: 3 register tiles + 33 NOR + 1 CONST, 38/38
  nets routed, 613 bridge crossings). Tests: `place_and_route/test_pnr_register.py` (12) and 4 new
  cone/keep-register cases in `synth/test_register.py`.
- HONEST CAVEAT: `REG_W`/`REG_H` are a footprint RESERVATION. The exact in-tile track-and-signal
  geometry of a register tile (the physical master-slave latch and its clock tap) is NOT solved in
  game and is TODO(human), exactly as the combinational NOR footprint was reserved before its
  geometry was proven in game. Placement, routing, DRC, emission and reconstruction all close
  around the reservation; only the in-game register tile geometry is open (STUCK.md).

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

### M5, a whole CPU. The Fibonacci accumulator machine CLOSES AS LOGIC IN SOFTWARE; the backend does not route it DRC-clean at this scale.

The sequential toolchain (the m.d.sync -> register + NOR path, the register place-and-route) was
de-risked on a toggle and a counter; this is the real clocked design it was built for: a minimal
8-bit ACCUMULATOR CPU that fetches and executes a hardwired program and emits the Fibonacci
sequence on a memory-mapped output latch. `hdl/cpu.py`, tests in `hdl/test_cpu.py` (20, all green).

- Lean by design (state is the scarce resource on the train substrate). The whole architectural
  state is 54 register bits: ACC(8) + PC(4) + Z(1) + phase(1) + IR_op(4) + IR_arg(4) + DMEM(4x8=32).
  NOT a CHIP-8, NOT a wrapper on the 891-NOR ALU.
- Six-opcode ISA (8-bit word, opcode high nibble, 4-bit operand low nibble): LDI imm, ADD addr,
  SUB addr, STA addr (writes a scratch reg or the OUTPUT latch), BZ addr (branch if zero),
  JMP addr. A two-phase FETCH/EXEC FSM. The datapath REUSES the ripple-carry full adder and the
  sub = x + ~y + 1 trick from hdl/adder.py / hdl/alu.py (add/sub/pass only, not the whole ALU), a
  one-hot opcode decode like alu.py's, a wide-NOR zero flag, and a result mux into ACC. The ROM is a
  hardwired pc-indexed multiplexer; DMEM is an addressed register file.
- Three views, the same discipline as the adder/ALU: a plain Python `cpu_reference` (the
  architectural ground truth), a behavioural Amaranth `Cpu` (m.d.sync registers), and a structural
  gate + DFF `build_cpu_netlist` (1515 NOR + 54 DFF + 2 const = 1571 cells structural; lowering to
  the buildable set with `to_nor(keep_registers=True)` gives 1575 NOR + 54 register tiles = 1631).
- Verified, by running, NOT asserted: all three views (and the all-NOR lowering, and the netlist
  RECONSTRUCTED from its own placement) emit exactly 1,1,2,3,5,8,13,21,34,55,89,144,233 (the 13
  eight-bit Fibonacci terms) then the mod-256 overflow term 121, and free-run the recurrence mod 256
  after. The structural netlist steps CYCLE-FOR-CYCLE IDENTICALLY to the behavioural Cpu across every
  exposed bit (ACC, PC, Z, phase, the out_we strobe and the out_port value) over 80 edges. Each of the
  six opcodes is exercised individually through both the reference and the structural netlist (LDI,
  ADD, SUB with mod-256 wrap and the zero flag, STA, BZ taken and not-taken, JMP).
- The Fibonacci loop is a neat trick worth noting: the window slide (A,B) -> (B, A+B) uses NO
  temporary, via the identity oldB = next - oldA (since next = oldA + oldB), so a single SUB does the
  slide and the whole program fits the 16-word ROM with a JMP.
- WHAT DOES NOT CLOSE (isolated, STUCK.md #8): the lowered CPU PLACES and ROUTES to 100 percent of
  nets (1632/1632) with the clock reaching every one of the 54 register tiles, but `drc()` reports
  ~410 route shorts at this size. These are a SCALE limit of the shared constructive channel router
  (`place_and_route/channel_route.py`, a pipeline contract this work must not modify), which exhausts
  its clear riser-column supply at ~1600 dense cells and takes its documented fallback. It is NOT a
  CPU flaw: the 92-cell adder and the 893-cell ALU both route DRC-clean through the same router. The
  CPU LOGIC is fully verified; the DRC-clean-at-scale routing is the open backend item, with three
  concrete router-side fixes noted in STUCK.md #8.

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
