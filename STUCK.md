# STUCK

Isolated hard problems for the human. Each entry is what is blocked, what was tried, the
exact failure where there is one, and the concrete next step. Plain tone, no em-dashes.

The short version: everything that can be proven in software is proven (see STATUS.md), and the
single hardest piece the brief flagged, a logic gate that actually computes inside OpenTTD, is
SOLVED and independently verified (a 2-input NOR, truth table 1,0,0,0). Gate COMPOSITION is now
also verified in game: a two-gate chain computes OR(a,b) = NOT(NOR(a,b)), readout
`OR s40 39 41 41 41` giving 0,1,1,1 = OR (scenarios/norchain_gs/). A clock train (a train looping
with a stable period) and live re-evaluation of a gate on the same tiles (input poked live, output
follows, no rebuild, readout `REEVAL s46 52 45 52`) are also verified in game
(scenarios/clockgate_gs/). What remains is tying the clock and re-evaluation together into a
RELIABLE synchronous gate (a pure clock-driven release interlock plus a one-edge output register;
the GS-mediated version works intermittently but did not survive independent re-verification), then
the framebuffer readout and folding the gate geometry into the place-and-route emitter. Those are
engineering on working, verified pieces, not unknowns.

## 1. The physical OpenTTD NOR gate geometry. SOLVED for a single combinational gate AND a 2-gate chain.

RESOLVED (the single-gate part). A single NOT (one-input NOR) and a single 2-input NOR were
built in OpenTTD 15.3 and PROVEN to compute by poking the input(s) and watching the output
flip, all from a GameScript. The 2-input NOR was INDEPENDENTLY re-verified by the orchestrator
(see below), since the agent's original GSLog evidence could not be reproduced (GSLog does not
relay reliably to the admin port here). Verified truth tables:

    NOT:  A=0 -> 1,  A=1 -> 0          (one physical gate poked twice)
    NOR:  00 -> 1, 01 -> 0, 10 -> 0, 11 -> 0   (all four combos on one structure)

Re-verification (relay-independent): the gate encodes the four raw reader-train x positions into
the COMPANY NAME, read back with `rcon companies` (`scenarios/norgate_gs/main_verify_byname.nut`).
A fresh run returned `NORFX sig46 51 45 39 39`: the reader passed the signal (x=51 > 46) only for
inputs 00 and was held (x <= 46) for 01/10/11, so output = (reader passed) = 1,0,0,0 = NOR,
judged from the raw positions, not from the GameScript's own pass/fail logic.

The working GameScript is `scenarios/norgate_gs/` (main_not_poke.nut, main_nor2.nut). The bit
is train-presence on a piece of track; a block signal is red iff its block is occupied, so a
reader train passes the signal iff every input is absent, which is NOR. The output is observed
by where the reader ends up (`GSVehicle.GetLocation`), because the GS API exposes no signal
aspect read and GSTile cannot detect a vehicle on a tile.

The two coordinate-level facts that took the longest (both verified, not guessed):
  - `GSRail.BuildSignal(tile, front)` builds a signal that permits travel FROM `front` INTO
    `tile`. To let an EASTBOUND reader pass a signal at SIGX you pass front = SIGX-1 (the tile
    the train comes from), the OPPOSITE of the naive guess. front = SIGX+1 makes a westbound
    signal whose red back blocks the reader unconditionally and looks like a dead gate.
  - The signal's protected block must be a through block. A normal block signal in front of a
    dead-end block (e.g. straight into a depot) stays red even when empty. Terminate the input
    block with a SECOND signal so the reader signal guards a real block.
  - Plus: the build area must be flat and water-free (a random map drops lakes on the fixed
    coordinates and rail will not build on water). The GS demolishes + LevelTiles its rectangle
    first; `tools/sav_writer.py` flatten() is an alternative.

Exact geometry, the verbatim truth tables, and the run procedure are in
`scenarios/GATE_DESIGN.md` (the "SOLVED AND VERIFIED" section) and
`scenarios/norgate_gs/readme.txt`. The gate is reproduced by running scenarios/norgate_gs/ (or the relay-independent
main_verify_byname.nut) on a fresh dedicated server.

NOW ALSO RESOLVED: gate COMPOSITION. A two-gate chain computing OR(a,b) = NOT(NOR(a,b)) was built
and verified in game (`scenarios/norchain_gs/`). Gate 1 (a 2-input NOR of a,b) feeds gate 2 (a NOT):
gate 1's reader, when it passes (output 1), is frozen on a coupling tile CPLX that is joined by a
signal-free spur into gate 2's input block, so gate 1's output physically parks a train in gate 2's
input; gate 2's reader then passes iff gate 1 did not. A fresh dedicated-server run, read via the
company name, returned `OR s40 39 41 41 41` (SIG2X=40, reader x>40 == OR 1). Judged from the RAW
positions: 00->39 (OR 0), 01/10/11->41 (OR 1) = 0,1,1,1 = OR(a,b), exactly. INDEPENDENTLY RE-VERIFIED by the orchestrator in a third fresh dedicated-server run: same readout `OR s40 39 41 41 41`, with live intermediates `c00 42/39` (gate1 passed, gate2 held) and `c01 35/41` (gate1 held, gate2 passed), judged from the raw positions to 0,1,1,1 = OR. The output bits come only from GSMap.GetTileX of the gate2 reader trains; there is no Squirrel-side OR/AND (source audited). Two facts were the crux,
both isolated empirically (norchain_gs/main_diag3.nut): the dead-end "hold" signal does NOT cleanly
park the passing reader, so it is parked by freezing it the moment its x reaches CPLX; and tearing
trains down between cases on the coupled junction hangs the script, so each of the four cases is a
SEPARATE chain copy at its own band of rows, with no teardown.

NOW ALSO RESOLVED: the CLOCK TRAIN and LIVE RE-EVALUATION on the same tiles (scenarios/clockgate_gs/).
  - Clock train (sub-goal 1, VERIFIED). A single train circulates a small closed rectangular rail
    loop forever (corner curve pieces are the same constants as the norchain spur), producing a
    periodic edge. Proven by sampling the train tile (x,y) at fixed wall-clock intervals and
    streaming the samples into the company name: across six consecutive laps the position swept the
    loop and recurred with a stable period of ~26 sample-intervals (departure-edge idx 107,133,160,
    186,213,238; per-lap 26,27,26,27,25; the +/-1 is the discrete-poll alias). See main_clock.nut.
  - Live re-evaluation on the SAME tiles (sub-goal 2, VERIFIED). One NOT gate (the norgate
    primitive) is built ONCE and read three times while it stays built, changing only the input:
    input absent -> reader passes (x=52), poke an input train on the tap (no rebuild) -> reader held
    (x=45), remove it -> reader passes again (x=52). Readout `REEVAL s46 52 45 52` (sig at 46),
    reproduced on a fresh run. The output followed the live input on the same physical gate.
    Two teardown facts found here: a normal one-way block signal blocks the return trip (so a reader
    cannot ping-pong back through the gate; each read uses a fresh eastbound reader), and a reader
    HELD at a red signal cannot be sold (SellVehicle needs a depot), so a held reader is freed by
    removing the input first, then disposed in the east depot. See main_reeval.nut.

STILL OPEN (the rest of the machine), now resting on a further-verified foundation:
  - Clock-SYNCHRONISED sampling (sub-goal 3, NOT VERIFIED, unreliable). main_sync.nut ties each gate
    sample to the clock train's passage (the GS waits for the clock to enter the loop top run, then
    samples). The build agent saw the gate output track a driven input schedule in two of its runs
    (schedule 001100 -> output 110011 = NOT at each edge, each edge released by a clock wait, never
    the timeout). BUT independent re-verification could NOT reproduce it: a fresh-run verifier got
    zero clock-released edges in three tries (the clock train stalled, "clkOK-stuck" twice and
    "clkSTUCK" once), so the consolidated output never appeared. Treat sub-goal 3 as UNRELIABLE and
    UNCONFIRMED, not proven. What is missing and why it is fragile: the release is GS-mediated (the
    GameScript polls the clock and dispatches the reader), there is no pure track-signal interlock (a
    clock-driven signal physically releasing a waiting reader with no GS in the release path), there
    is no physical one-edge output register, and the clock loop is not perfectly self-sustaining (its
    two cycling orders occasionally park the train, and per-edge reader disposal can jam the lane).
    The clock train and the live re-evaluation below it ARE verified; tying them together reliably is
    the remaining hard piece.
  - Multi-input NOR with 3+ inputs (the 2-input case is proven; wider fan-in is the same idea,
    all taps in one protected block, but was not built/verified here).
  - Wiring the per-net output train-presence into the framebuffer signal tiles for the viewer.
  - Folding this geometry into `scenarios/openttdoom_gs/main.nut::StampCell` (still a placeholder)
    so the place-and-route pipeline stamps computing cells, not just visible structure.

Concrete next step: replace the GS-mediated clock release in main_sync.nut with a pure track-signal
interlock (a clock pulse on a shared block that opens a reader's release signal once per lap), add a
physical output-register block holding the value for a full period, and make the clock train's loop
self-sustaining so a chain settles with one edge of latency (matching scenarios/gate_model.py). The
single-gate geometry, the observability trick, gate composition, the clock train, and live same-tile
re-evaluation are now all known and working.

### Update (scenarios/syncgate_gs/): a more-reliable clock (but flaky on launch); the pure interlock is the precise blocker.

A follow-on de-risk (scenarios/syncgate_gs/) attacked exactly the "concrete next step" above. Two
things were settled, both judged from RAW positions read via the company name, GS observing only.

PARTLY RESOLVED: a SELF-SUSTAINING CLOCK that, once running, locks to a stable period. The design is
ONE-WAY NORMAL block signals around the loop (one per side, clockwise), not a plain unsignalled loop
with plain-tile waypoint orders. A single train on a one-way-block-signalled loop reserves block-by-
block forward, cannot mutually deadlock (it is the only train), and never re-enters the depot (a one-
way signal's back is solid). When it launches it circulates many laps with the period locked at 35-36
sample-intervals (15 ticks each, so ~525 ticks), one run reaching 17 laps. HONEST RELIABILITY CAVEAT:
the build agent reported 3/3, but independent re-verification got only 3 of 5 fresh runs. The two
failures were both at LAUNCH, not steady state: once the clock train left the depot it always locked
to the stable period, but in run 2 it stalled oscillating at the depot exit (never left) and in run 4
the vehicle never built at all ("NOVEH"). So the clock CONCEPT and steady-state period are solid, but
the launch sequence (build vehicle, leave depot onto the signalled loop) is itself flaky and is an
open reliability item. Also pinned: the earlier "clock stalls at ~lap 5" symptom was NOT the clock, it
was the COMPANY-NAME LENGTH LIMIT (~31 chars): a growing readout string overflowed, SetName silently
no-opped, and the DISPLAYED name froze while the script and train ran on. Bounded short name == fix.
(Second gotcha: only ONE admin connection at a time; a concurrent rcon resets a held poller's socket.)

STILL BLOCKED, with the precise mechanism now pinned: the PURE RELEASE INTERLOCK. To release the
reader by clock-block occupancy with no GS in the timing path, the reader's release signal must READ
the clock block's occupancy, which requires connecting the reader's signal network to the clock
block. In OpenTTD 15.3 that connection couples the RESERVATION graph too, so a circulating reader
makes the clock's mandatory loop tile (the clock block, on its bottom run) unreservable and the clock
either never leaves its depot or stalls on the clock block (observed: cL=0 the whole run, reader
free-running). THREE distinct read mechanisms were built and all failed this way:
  - STAGE 2, block-merge read (a stub crossing merges the clock-block tile into the reader's release
    block): SYMMETRIC, so the reader holds the clock. Clock could not launch (stuck in depot, cL=0).
  - STAGE 3, presignal read (reader release = ENTRY presignal; an EXIT presignal at the stub top
    faces the clock block, so entry-green iff clock-block-clear, intended to read the aspect WITHOUT
    merging reservation): in 15.3 it still coupled. Clock could not launch (cL=0).
  - STAGE 4, PBS clock + block-merge read (one-way PBS path signals on the clock loop, so the clock
    reserves track-by-track): the clock DID leave the depot and reach the clock block, then STALLED
    ON the clock block (could not reserve out while the reader circulated through the merged region),
    and the merge did not hold the reader, which free-ran past the release (cL=0, P rising). Coupling
    relocated from the depot to the clock block, not removed.
This is exactly the risk all three research proposals flagged: "the shared clock block must be
read-only to readers, or the clock can be metered to a halt." A pure-signal occupancy read that does
NOT couple reservation was not found in 15.3 here. Concrete next directions for the human, none built:
  (a) take the clock block OFF the clock's mandatory path, e.g. the clock drives onto a short reverse
      SPUR (the clock block) and backs out, so a coupled reader cannot block the main loop;
  (b) two (or more) clock trains so the loop is never fully blockable by one coupled reader;
  (c) a genuinely one-directional detector (verify whether a two-way exit-signal back-face read can be
      arranged so reservation flows only clock->reader, never reader->clock).
The reliable clock and the verified single-gate read are the working foundation to build these on.
Files: scenarios/syncgate_gs/ (main.nut STAGE 1/2/3, readme.txt, poll.py, run2.sh, rel3.sh).

## 2. GameScript runtime and observability. MOSTLY RESOLVED, with one caveat.

The GS runtime IS available and was used extensively. A dedicated server (`openttd.exe -D`)
opens an admin TCP port (3977); `tools/ottd_admin.py` runs console commands (rcon) and reads
state back. GameScripts load by name from the OpenTTD `game/` dir (the config `[game_scripts]`
entry must use the GS GetName with NO spaces, a real gotcha that silently disabled loading). A
company for the deity GS to build as is created with the rcon command `start_ai`. This rig built
and ran the openttdoom builder, the direct-save renders, and the verified NOR gate.

The one caveat: GameScript `GSLog` output does NOT relay reliably to the admin console here (the
GS runs, builds, and its company money drops, but the GSLog lines do not arrive). So results must
be read through a different channel: encode them into the company name (read via `rcon companies`,
see `main_verify_byname.nut`), or into on-map signs / a saved game, or screenshot the result. The
gate verification used the company-name channel for exactly this reason.

What was fixed by actually running it (not static checks): the no-space GS name, the company
build-context (start_ai), maxing the loan to afford builds, a valid rail-type selection, and
building offset from the map edge. See `tools/ottd_render.py` for the full working recipe.

## 3. GameScript company build-context (deity problem).

Blocked: a GameScript runs as a deity with no company, and `GSRail.BuildRailTrack` /
`GSRail.BuildSignal` require a valid company entered via `GSCompanyMode`. The GS API docs are
explicit ("Commands cannot be executed in deity mode",
https://docs.openttd.org/gs-api/classGSCompanyMode). So as written, every build call may be
rejected and nothing stamps.

Where it sits: `main.nut::PickCompany` borrows `GSCompany.COMPANY_FIRST`, which is unverified
and will not resolve if no company exists in the game.

Concrete next step (decision for the human): either run the GS in a game that already has a
company and borrow it, or have the scenario found a company first, or investigate whether
deity-built or town-owned rail is acceptable for a pure-logic map where the economy is
irrelevant. Documented as `TODO(human)` in `main.nut`.

## 4. GameScript bridge construction detail. (Routing itself is now solved.)

The routing completeness problem is RESOLVED. The old maze router topped out near 77 of 101
nets on the 4-bit adder. The cause was topological, not a weak heuristic: a 4-bit adder is not
planar, so some wire crossings are unavoidable, and a tile-disjoint (no-crossing) router can
never reach 100 percent. OpenTTD crosses tracks with bridges, so the router was replaced with a
deterministic channel router (`place_and_route/channel_route.py`) that crosses nets only as
perpendicular bridges. All adders now route to 100 percent, DRC clean, logic preserved (the
4-bit adder uses 1958 bridge crossings on a 1024x256 map). The bridge tiles are carried in
`Route.bridges` and flow through `Scenario.to_nut()` to the GameScript.

What remains (the in-game build detail): `scenarios/openttdoom_gs/main.nut::LayBridge` calls
`GSBridge.BuildBridge` for each bridge tile, but the exact bridge type selection, the head and
ramp tile orientation, and the one-way signal placement that keeps the carried track moving need
in-game calibration. The crossing data is computed and correct; turning each crossing into a
built bridge with the right ramps is the open piece, and it depends on the same gate and clock
timing that blocker 1 is about. Marked `TODO(human)` in `main.nut`.

## 5. The full yosys NOR techmap. RESOLVED.

The proper "read verilog, synth, techmap to NOR" flow now works. A full yosys from oss-cad-suite
is installed, and `synth/yosys_synth.py` runs it end to end: it emits `synth/adder4.v` from the
behavioural amaranth `Adder4`, runs `synth/adder4.ys`, and imports the result. yosys techmaps the
adder to 62 buildable cells (NOR plus NOT, where NOT is a one-input NOR), which adds over all 512
input combinations and is `equivalent()` to the Python `to_nor()` netlist (yosys abc is tighter,
62 vs 92 cells). `synth/test_yosys.py` checks this and skips cleanly when yosys is absent.

One environment wrinkle, handled: this Windows yosys build's liberty-to-genlib conversion fails
("merged SCL conversion failed"), so the script maps with abc's built-in NOR set (`abc -g NOR`)
rather than `abc -liberty synth/nor.lib`. Same buildable result. `synth/nor.lib` is kept for
yosys builds where the liberty path works. The tool-free Python `to_nor()` remains the default
so the core pipeline needs no external tools.

## 6. An OpenTTD source build is not done here (no C/C++ compiler).

A recorded environment fact, not a blocker. This machine has no C or C++ compiler, so OpenTTD was
not built from source; we use the prebuilt binary, which satisfies M0 (headless start with
OpenGFX). yosys and verilator ARE now available (oss-cad-suite, see blocker 5), so the only piece
of the brief's toolchain that needs a compiler is a from-source OpenTTD build, and that is only
needed for the speed fork, which is explicitly out of scope. `scripts/setup.sh` documents the
CMake source-build steps for a human who wants them.
