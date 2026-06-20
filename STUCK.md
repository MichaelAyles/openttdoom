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

## 4. The router does not reach 100% on multi-bit adders.

Blocked: full physical routing. The crude maze router routes about 77 of 101 nets on the
4-bit adder (DRC clean, no shorts, logic verified). Unrouted nets are recorded honestly in
`RouteResult.unrouted` and surfaced by `unrouted_nets()`. This is a completeness gap, not a
correctness one: logical equivalence is independent of routing completeness, and the brief
explicitly allows crude routing.

What was tried (by the place-and-route build, in order): plain greedy Lee/BFS; escape-tile
pin reservations; channel widening and demand-sized channels; barycenter row placement;
negotiated-congestion (Pathfinder-style history penalty, the best general result); rip-up and
reroute (made it worse, cascading rips, reverted); a deterministic per-net dedicated-track
router (0 shorts but low coverage on far-column consumers, removed). A later probe doing
repeated legalisation orders on the 4-bit adder's 1024x256 map ran over 90s with no result,
so router experimentation thrashes at this size and was stopped to protect the correctness
fixes.

Concrete next step: a proper channel / track-assignment router. The placement already
guarantees strict left-to-right signal flow with clear footprint-free gap rows and columns, so
assign each net its own vertical track column and horizontal highway row in those gaps. This
is a from-scratch rewrite of `place_and_route/route.py` and should be its own task with its
own test budget.

## 5. The full yosys NOR-liberty techmap.

Blocked: the classic "read verilog, synth, `abc -liberty nor.lib`" flow that maps an adder to
a NOR-only cell library with a real yosys.

Why: the only yosys reachable here is the WASM build bundled with `amaranth-yosys`
(pip-installed, 0.50). It is stripped: no `read_verilog`, no `techmap`, no `abc`, no `synth`
(confirmed, `read_verilog` returns "No such command"). It can read amaranth RTLIL, run
opt/simplemap, and write JSON, nothing more.

What was achieved instead: the WASM yosys does a genuine gate-level decomposition of a
bit-level adder (8 XOR, 8 AND, 4 OR cells), which is imported and verified over all 512 combos
as a cross-check. The final NOR techmap is done by `Netlist.to_nor()` in Python, which is
exact and exhaustively verified. So the buildable NOR netlist is real and correct, it just
does not come from a yosys techmap.

Concrete next step: `synth/adder4.ys` is the complete proper-yosys script with the NOR liberty
snippet inline and run instructions, marked `TODO(human)`. Run it under a full yosys from the
oss-cad-suite bundle (URL in `scripts/setup.sh`). Its output should be `equivalent()` to
`synth/out/adder4_nor.json`.

## 6. yosys, verilator and an OpenTTD source build are not installed here.

Not a blocker, a recorded environment fact. This machine has no C or C++ compiler, so OpenTTD
was not built from source (we use the prebuilt binary) and verilator is absent. yosys proper
is absent too (only the stripped WASM one above). The verified pipeline does not depend on any
of them. `scripts/setup.sh` documents the oss-cad-suite bundle (yosys plus verilator) and the
CMake source-build steps for a human who wants the full toolchain.
