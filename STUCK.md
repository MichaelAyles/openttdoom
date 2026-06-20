# STUCK

Isolated hard problems for the human. Each entry is what is blocked, what was tried, the
exact failure where there is one, and the concrete next step. Plain tone, no em-dashes.

The short version: everything that can be proven in software is proven (see STATUS.md). The
real blocker is the physical OpenTTD gate, which the brief flagged as the hardest piece. It
is genuinely unsolved, not faked. The pipeline around it is complete and waiting for it.

## 1. The physical OpenTTD NOR gate geometry. THE hard one.

Blocked: the exact tile-by-tile track and signal layout of a single clocked NOR tile that
actually computes in OpenTTD, expressed as the `(x, y, track-piece, signal-type, front-tile)`
tuples a script can stamp.

Why it is hard: the logic is understood at the signal level (see `scenarios/GATE_DESIGN.md`:
two-way signals read a bit without consuming it, entry/combo presignals evaluate a boolean
over block occupancy, a clock train gives one-edge latency). What is missing is the concrete
geometry. The reference constructions exist as screenshots and old savegames, not as
coordinates:

- zem.fi, http://zem.fi/2005-10-21-ttd-logic. The NOR there additionally relied on NPF
  pathfinder behaviour that differs across OpenTTD versions, so it is not a drop-in for 15.3.
- openttdcoop wiki Logic, https://wiki.openttdcoop.org/Logic, and the optimised-gate blog
  posts. The wiki Logic page and the blog posts returned HTTP 500 during this run, so the
  compact optimised-gate exact tile counts could not be pulled from primary source. The
  4x4 to 8x8 footprint estimate in GATE_DESIGN.md is a planning estimate, not a measurement.

What was tried: all reachable reference pages were fetched and read for the signal mechanism
(the OpenTTD signals manual and the junctionary advanced-signalling page filled in for the
500ing pages). No source gives a coordinate-level layout.

Where it sits in code: `scenarios/openttdoom_gs/main.nut`, function `StampCell`. It currently
lays one placeholder straight per pin so routing has something to attach to, and is explicitly
marked as not computing. Every sub-piece (input tap with two-way read signal, the
presignal NOR evaluation, the output register track, the clock-release tap) has a `TODO(human)`.

Concrete next step: build one NOR tile by hand in OpenTTD 15.3, confirm it computes when
poked, then read its tiles back out (or measure them) into the `StampCell` geometry. Once one
tile is solved, the rest of the pipeline already knows how to place and wire many of them.

## 2. The GameScript cannot be run or verified in this environment.

Blocked: confirming `scenarios/openttdoom_gs/` loads and builds in OpenTTD.

Why: there is no OpenTTD GameScript runtime here. The bundled headless `openttd.exe` is the
GUI-subsystem Windows release, which does not pipe stdout back to the shell, so even a GS that
logs via GSLog cannot be observed from this environment, and there is no way to interactively
poke inputs and read outputs. `main.nut` is therefore unverified Squirrel: its brackets
balance and its API names follow the documented GS API, but it has never been loaded by
OpenTTD.

What was tried: static checks only (bracket balance, API-name cross-reference against the GS
API docs). One real bug was found and fixed by static reading: an operator-precedence error in
`PickCompany` (`!GSCompany.ResolveCompanyID(c) == COMPANY_INVALID` parsed wrong).

Concrete next step: `scenarios/openttdoom_gs/readme.txt` has the install-and-run procedure.
Copy the directory into an OpenTTD `game/` folder, select it under Settings then Game Script,
start a game, and watch the console (`reload_game_script`, `debug_level script=4`). Fix the
Squirrel against real loader errors from there.

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
