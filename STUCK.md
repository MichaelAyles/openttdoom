# STUCK

Isolated hard problems for the human. Each entry is what is blocked, what was tried, the
exact failure where there is one, and the concrete next step. Plain tone, no em-dashes.

The short version: everything that can be proven in software is proven (see STATUS.md), and the
single hardest piece the brief flagged, a logic gate that actually computes inside OpenTTD, is
now SOLVED and independently verified (a 2-input NOR, truth table 1,0,0,0, confirmed via an
alternate readout channel). What remains is composing many gates into the clocked machine: the
clock train, gate-to-gate chaining with one-edge latency, framebuffer readout, and folding the
gate geometry into the place-and-route emitter. Those are engineering on a working foundation,
not unknowns.

## 1. The physical OpenTTD NOR gate geometry. SOLVED for a single combinational gate.

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

STILL OPEN (the rest of the machine), now resting on a verified foundation:
  - Multi-input NOR with 3+ inputs (the 2-input case is proven; wider fan-in is the same idea,
    all taps in one protected block, but was not built/verified here).
  - The clock train. The verified gate is combinational (a reader is run on demand). The
    synchronous design needs a clock that releases reader sampling on a shared edge so a chain
    settles predictably. Not built.
  - Composition: feeding one gate's output (a parked output train) into the next gate's input
    block, and the one-edge register latency. Not built.
  - Wiring the per-net output train-presence into the framebuffer signal tiles for the viewer.
  - Folding this geometry into `scenarios/openttdoom_gs/main.nut::StampCell` (still a placeholder)
    so the place-and-route pipeline stamps computing cells, not just visible structure.

Concrete next step: extend the proven `norgate_gs` construction to chain two NOR gates (output
train of gate 1 parked in the input block of gate 2) and add a clock train, then verify a 2-gate
chain computes with one edge of latency. The single-gate geometry and the observability trick
are now known and working.

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
