# OpenTTD speed fork for openttdoom

The train-built machine runs far too slowly in stock OpenTTD to finish a frame. The headless
null-video driver is already uncapped (it runs flat out), so the win is not uncapping, it is
making each game tick cheaper by stripping per-tick work that is useless on a pure-logic map
(trains and signals only, no economy, towns, industries, cargo or news).

This is a prototype. It establishes the lever, measures it honestly on real runs, and leaves a
clear note on the next, deeper lever. The fork is minimal and reversible, gated behind a runtime
flag so the exact same binary runs both stock and stripped, which is what makes the comparison
honest.

## Result, measured

Same binary, same map, the only difference is the flag. Default 256x256 empty map (`-vnull`
generates a fresh default-size map), null video/sound/music, `-x` to exit after the run.

| mode | command | ticks | seconds (two runs) | ticks/sec |
| --- | --- | --- | --- | --- |
| stock (flag off) | `openttd_fast.exe -x -vnull:ticks=300000 -snull -mnull` | 300000 | 61.983, 69.061 | ~4578 |
| logic-map (flag on) | `OTTDOOM_LOGIC_MAP=1 openttd_fast.exe -x -vnull:ticks=300000 ...` | 300000 | 22.522, 20.145 | ~14065 |

Speedup: 65.52s / 21.33s = 3.07x (averaging the two runs in each mode). Per single best runs it
is 61.983 / 20.145 = 3.08x. Cross-check against the stock SOURCE build (a separate binary, flag
absent entirely): 300000 ticks in 58.799s = 5102 ticks/sec, in the same band as the fork's
stock mode, confirming the flag-off path is genuinely stock.

The runs above are wall-clock `time` on real headless executions, pasted verbatim from the shell.
Nothing here is modelled or extrapolated.

### Independent re-measurement (2026-06-21)

The claim above was reproduced from scratch on a separate session, by a different operator, on
the same box. The OpenTTD tree was rebuilt incrementally first (the binary came out byte-identical,
md5 `0135ceb0fe9f633b00ddc217a4019407`, confirming `openttd_fast.exe` is genuinely built from the
source edits in `src/openttd.cpp` and `src/landscape.cpp`, the only two files the fork touches).
Both modes were timed three times each at 300000 ticks, plus the prebuilt `openttd.exe` as a fully
independent baseline. All runs were isolated copies managed by PID (no `taskkill`, port 3977 never
touched). Raw seconds, pasted from the shell:

| mode | binary / flag | seconds (3 runs) | avg sec | ticks/sec |
| --- | --- | --- | --- | --- |
| fork, flag off | `openttd_speedtest.exe` (unset) | 59.837, 58.812, 62.459 | 60.369 | 4969 |
| fork, flag on | `openttd_speedtest.exe` `OTTDOOM_LOGIC_MAP=1` | 19.701, 19.047, 20.598 | 19.782 | 15165 |
| prebuilt baseline | `openttd.exe` (no fork code) | 66.493, 76.184 | 71.338 | 4205 |

**Speedup, same binary, only the flag differs: 60.369 / 19.782 = 3.05x** (best single runs
58.812 / 19.047 = 3.09x). Against the prebuilt baseline the ratio is even larger, 71.338 / 19.782
= 3.61x, but that baseline binary is a different build (it ran slower and noisier), so the honest,
apples-to-apples number is the same-binary 3.05x.

Causation was nailed with a control: running the prebuilt baseline (which has no fork code) WITH
`OTTDOOM_LOGIC_MAP=1` set gave 66.542s, identical to its flag-off runs. The env var does nothing
without the source edits, so the 3x is genuinely the tile-loop / landscape-tick strips, not an
environment or measurement artifact. Verdict: the 3.07x claim reproduces, measured 3.05x.

### Honest scope of the win

This was measured on an empty default map, where the dominant per-tick cost is the tile loop
(see below) and there are no vehicles. On the real openttdoom machine map the vehicle tick
(every train, plus its signal reservation and pathfinding) will be a large and growing share of
each tick, and that work is deliberately KEPT (it is the machine). So as the train count climbs,
the vehicle tick will increasingly dominate and the ratio this strip delivers will shrink from
3x toward 1x. The strips here remove the fixed map-housekeeping overhead, which is the right
first lever and a real 3x on a bare map, but the next lever is vehicle/pathfinding surgery, not
more housekeeping strips. See "Next lever" below. Do not overclaim a flat 3x on the full machine.

## What was stripped, and why each is safe for a logic map

A logic map is rail track plus signals plus the clock and reader trains. It has no towns, no
industries, no stations, no cargo, no economy, no news, no trees that matter. The strips target
exactly the per-tick subsystems that serve those absent features.

1. **`RunTileLoop()`** (the big one). Every tick this calls `tile_loop_proc` on `mapsize / 256`
   tiles (256 calls/tick on the default 256x256 map, 1024/tick on the adder's 1024x256 map),
   chosen by an LFSR walk so every tile is visited once per 256 ticks. For the tile types a
   logic map actually has, the proc does only cosmetic ground work:
   - `TileLoop_Clear` (src/clear_cmd.cpp:258): ambient sound, grass density growth, snow/desert
     ground type, farm fences. Nothing here changes a tile's usability.
   - `TileLoop_Track` (src/rail_cmd.cpp:2595): sets the rail *ground appearance* (snow/desert/
     grass/water under the rails). It never touches the track bits, the signal state, or
     anything a train reads to move. Train motion and signal logic read the map arrays
     (MAP5/MAP8 track and signal bits) directly, not via the tile loop.
   So skipping the tile loop changes only how the ground looks, never whether a train moves or a
   signal computes. On a logic map it is pure waste, and it is the single largest fixed per-tick
   cost. This is where most of the 3x comes from.

2. **`OnTick_Town()`, `OnTick_Trees()`, `OnTick_Station()`, `OnTick_Industry()`** inside
   `CallLandscapeTick()` (src/landscape.cpp). Town/Station/Industry iterate their entity lists,
   of which a logic map has zero, so they are already cheap, but the call overhead and (for
   Trees) the random tree planting on the map are removed. `OnTick_Trees` actively plants trees
   on random tiles (`PlantRandomTree`), which is both wasted work and undesirable map mutation on
   a logic canvas. Skipping all four is safe precisely because there are no towns, stations,
   industries or cargo to service. `OnTick_Companies` and `OnTick_LinkGraph` are KEPT (they are
   cheap and harmless, and link-graph touches nothing on a cargo-free map).

What is explicitly KEPT, because it is the machine or is load-bearing:
- `CallVehicleTicks()` in full: every train ticks, including the clock train and reader trains.
- All signal, reservation and pathfinding logic (untouched).
- `AnimateAnimatedTiles()` (already O(animated tiles) = 0 on a logic map, no need to gate).
- `CheckCaches()` (already early-returns in Release: `_debug_desync_level <= 1`, src/cachecheck.cpp:40).
- The calendar/economy/tick timers (`TimerManager<...>::Elapsed(1)`), which are cheap counters
  and which the GameScript-mediated clock and date logic may rely on.

## Source changes (in the OpenTTD tree at C:/Users/mikea/openttd-build/OpenTTD, NOT in this repo)

All three edits are guarded by one runtime flag, `_ottdoom_logic_map`, set from the environment
variable `OTTDOOM_LOGIC_MAP`. Unset or `0` gives byte-for-stock behaviour; `1` enables the strips.
Using an env flag (not a compile flag) means one binary runs both modes, so the timing comparison
is on the identical executable with only the flag differing.

1. `src/openttd.cpp`, file scope: define `bool _ottdoom_logic_map = false;` with the explanatory
   comment block.
2. `src/openttd.cpp`, `openttd_main()` (top): read the env var once at startup and set the flag
   (`if (std::getenv("OTTDOOM_LOGIC_MAP") ... ) _ottdoom_logic_map = true;`).
3. `src/openttd.cpp`, `StateGameLoop()` (GM_NORMAL path): wrap the tile loop call,
   `if (!_ottdoom_logic_map) RunTileLoop();`.
4. `src/landscape.cpp`, `CallLandscapeTick()`: declare `extern bool _ottdoom_logic_map;` and wrap
   the `OnTick_Town/Trees/Station/Industry` block in `if (!_ottdoom_logic_map) { ... }`.

All changes are small, local, and trivially reversible (delete the flag and the guards). The
editor game-loop path and the dedicated-server path are left stock.

## How to reproduce

Rebuild (incremental, deps cached; only the two touched files recompile), from a Windows cmd
batch because vcvars is a .bat:

    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
    set CMAKE_POLICY_VERSION_MINIMUM=3.5
    set VCPKG_KEEP_ENV_VARS=CMAKE_POLICY_VERSION_MINIMUM
    cd /d C:\Users\mikea\openttd-build\OpenTTD
    cmake --build build --config Release -j 4

The binary lands at `build\Release\openttd.exe`. Copy it into a complete runtime data layout so
it finds `lang/ baseset/ ai/ game/`:

    cp build/Release/openttd.exe \
       <repo>/vendor/openttd/openttd-15.3-windows-win64/openttd_fast.exe

Time both modes on the same map (run from inside that layout dir):

    cd <repo>/vendor/openttd/openttd-15.3-windows-win64
    # stock control:
    unset OTTDOOM_LOGIC_MAP;  time ./openttd_fast.exe -x -vnull:ticks=300000 -snull -mnull
    # stripped:
    export OTTDOOM_LOGIC_MAP=1; time ./openttd_fast.exe -x -vnull:ticks=300000 -snull -mnull

ticks/sec = 300000 / (real seconds). Use the same large tick count for both. Success is exit 0 and
wall-clock that scales with the tick budget (the Windows binary is GUI-subsystem so stdout is not
piped; the M0 smoke test confirms the loop ran: ticks=50000 -> 4.889s, ticks=150000 -> 10.861s,
both exit 0, time tracking the tick budget after the ~1s fixed startup).

## Isolation note (parallel track safety)

A parallel track uses the prebuilt `openttd.exe` and admin port 3977. This work never runs
`taskkill`, never touches port 3977, and runs only its own copied `openttd_fast.exe` /
`openttd_stock.exe` headless with `-x` (self-exiting, no admin port). The stock prebuilt
`openttd.exe` in the layout is left untouched.

## Next lever (do not skip this when scaling up)

The 3x here is the fixed map-housekeeping overhead. On the real machine map the per-tick cost is
dominated by `CallVehicleTicks()` -> `Train::Tick()` and, inside it, signal reservation and
pathfinding (NPF/YAPF) every time a reader or clock train hits a signal. That work is KEPT here
because it is the computation. The deeper speed lever, when train count makes the vehicle tick
dominate, is route/pathfinding surgery, for example:
- caching or precomputing the fixed reader/clock paths (the machine's track is static, so the
  pathfinder is recomputing a constant),
- a cheaper signal-block occupancy check for the known gate topology,
- reducing the per-train per-tick bookkeeping (cargo aging, sound motion counters) that is dead
  on a logic train.
Those are real engine surgery on the hot path and are the honest next step, not more
housekeeping strips. This prototype deliberately stops at the safe, measured, reversible win and
flags the next lever rather than overclaiming.

## Per-train lever, deepened (train-heavy map)

The housekeeping strip above was measured on a bare map with no vehicles, where it is ~3x. On the
real machine the per-TRAIN tick is what grows with train count, and that is what this section
attacks: it cuts the per-train post-tick bookkeeping that is dead weight on a logic train, behind
the same `_ottdoom_logic_map` flag, and measures it on a deliberately train-heavy map.

### The train-heavy benchmark map

There was no train-heavy save, so one was built with a small benchmark AI (a NoAI script,
`vendor/openttd/openttd-15.3-windows-win64/ai/LoopBench/`). It founds one company on a flat
256x256 map and stamps a dense grid of small closed rail loops, one engine-only train per loop,
with one-way PBS signals around each loop. One train per closed loop can never deadlock (it owns
the whole ring), so the trains circulate forever and each one exercises the kept hot path every
tick: `Train::Tick` -> `TrainController` movement, signal reservation, and the path reservation /
YAPF call at each PBS signal. Engine-only trains carry no cargo and stop at no station, so there is
no loading work, only the pure train tick.

The map has 153 to 158 such loops (so ~150 trains). After the trains spread out, a live readout
from the AI (logged over the admin port) shows ~85 to 92 of them moving at once, the rest still
accelerating out of their depots: e.g. `MOTION total=158 moving=92 avgspeed=21`. Motion was also
confirmed independently: two saves taken ten seconds apart differ only in the vehicle region, and
the deterministic re-run check below proves the trains advance.

Two variants of the save were built so the cut can be measured both ways:
- `loopbench.sav`: the logic-realistic map (smoke off, sound off, no economy), the settings an
  actual openttdoom logic map would use.
- `loopbench_cos.sav`: the same map but with default cosmetics on (`smoke_amount = 2`), to show the
  cut's value when the per-train cosmetic work is actually present (the default for a freshly built
  map that did not hand-disable smoke).

### What was cut, and why it is safe

The cut targets the per-vehicle, per-tick bookkeeping that runs AFTER the vehicle's own
`v->Tick()` and never feeds movement or pathfinding. All of it is gated by `!_ottdoom_logic_map`,
so flag-off is exact stock behaviour.

1. **`CallVehicleTicks()` per-vehicle bookkeeping** (src/vehicle.cpp). The loop calls `v->Tick()`
   (movement, signal reservation, pathfinding, KEPT) and then runs a per-vehicle switch that does
   only cargo aging (`AgeCargo` / `cargo_age_counter`) and the running-sound / motion-counter
   updates. None of it is read by movement: `motion_counter` is documented as "counter to
   occasionally play a vehicle sound" and is used only for sound and NewGRF visual variation; cargo
   aging affects cargo payment, and our trains carry none with economy off. Gated with a single
   `if (_ottdoom_logic_map) continue;` right after the `v->Tick()` call, so the whole cosmetic block
   is skipped on a logic map.
2. **`Train::ShowVisualEffect()`** (called in `TrainLocoHandler`, src/train_cmd.cpp). Smoke / steam
   plumes are purely cosmetic and, worse, each plume spawns an `EffectVehicle` that is then itself
   ticked every frame. On a headless logic map this is pure waste. Gated to
   `if (!mode && !_ottdoom_logic_map) v->ShowVisualEffect();`. (With `smoke_amount = 0` it already
   early-returns, so this bites only when cosmetics are on, which is exactly the `loopbench_cos`
   case.)

The vehicle's `Tick()` (the actual movement, the signal reservation, and the YAPF path call) is
left fully intact. No pathfinding was cached or skipped: that is the risky lever and is NOT done
here.

### Result, measured (same map, only the flag/binary differs)

Two binaries, same flag (`OTTDOOM_LOGIC_MAP=1`) on both:
- baseline = the housekeeping-only fork (`openttd_housekeeping.exe`, md5 `0135ceb0...`, the prior
  prototype with no per-train cut),
- optimized = housekeeping + this per-train cut (`openttd_fast.exe`, md5 `ab0cf3b6...`).

All runs are `OTTDOOM_LOGIC_MAP=1 <exe> -x -vnull:ticks=150000 -snull -mnull -c <cfg> -g <save>`,
three runs each, raw wall-clock seconds pasted from the shell. Startup/load is ~0.57s (measured at
ticks=100: 0.574s), so the sim-only ratio is slightly higher than the wall ratio.

| map | mode | seconds (3 runs) | avg sec | ticks/sec |
| --- | --- | --- | --- | --- |
| loopbench (smoke off) | baseline (housekeeping) | 4.337, 4.313, 4.360 | 4.337 | 34589 |
| loopbench (smoke off) | optimized (per-train cut) | 4.176, 4.193, 4.221 | 4.197 | 35741 |
| loopbench_cos (smoke on) | baseline (housekeeping) | 4.467, 4.493, 4.528 | 4.496 | 33364 |
| loopbench_cos (smoke on) | optimized (per-train cut) | 4.223, 4.198, 4.223 | 4.215 | 35587 |

**Speedup of the per-train cut, same flag, only the binary differs:**
- smoke off (logic-realistic): 4.337 / 4.197 = **1.033x** (~3.3% wall, ~3.7% on the sim portion).
- smoke on (default cosmetics): 4.496 / 4.215 = **1.067x** (~6.7% wall, ~7.5% on the sim portion).

For context on the same train-heavy `loopbench_cos` map, the full stack measured at 150000 ticks x3:
- stock (flag off, no fork at all): 5.147, 5.125, 5.222 -> 5.165s, 29043 tps
- housekeeping fork only: 4.496s, 33364 tps (1.15x over stock)
- housekeeping + per-train cut: 4.215s, 35587 tps (1.225x over stock, 1.067x over housekeeping)

Note the housekeeping strip is only ~1.15x here, not 3x: the trains add per-tick cost the tile-loop
strip does not touch, exactly as the "Next lever" section above warned. The per-train cut recovers
part of that. This is an honest, modest win, NOT a flat 3x, and it is larger when there is more
per-train cosmetic work to remove (6.7% with smoke vs 3.3% without).

### Correctness, proven deterministically

The cut must not change how trains move or path. This was proven, not asserted. The null video
driver runs exactly `ticks=N` and (with `autosave_on_exit`) writes `exit.sav` on exit, so the same
save run for the same tick count under each binary is bit-for-bit comparable.

Running `loopbench.sav` for 50000 deterministic ticks under the baseline binary and under the
optimized binary, the two `exit.sav` files are identical in size (879209 bytes) and differ in
exactly 632 bytes, all in the vehicle region (first diff at offset 799347). 632 / 158 trains =
exactly 4.0 bytes per train, and the differing bytes sit at the same offset within each ~231-byte
vehicle record: that is precisely the one `uint32 motion_counter` field per vehicle, the cosmetic
counter the cut stops updating. Every movement field (tile, x_pos, y_pos, direction, cur_speed,
subspeed, track, order progress) is byte-identical. The trains are in exactly the same places after
50000 ticks; only the sound counter differs.

Stability was also checked: 500000 ticks on the train-heavy map under the optimized binary exits 0
with no assert, desync or crash (13.464s).

### Honest scope and the remaining floor

This is a real, safe, reversible per-train win, but a modest one (3 to 7%). The reason is exactly
what the section above predicted: with the cosmetic bookkeeping gone, the remaining per-train cost
is the path reservation and YAPF call inside `v->Tick()`, which is KEPT because cutting it safely
is hard. On the benchmark the simple single-train rings have no junctions, so `ChooseTrainTrack`
extends a short reservation to the next PBS signal each time rather than running a full multi-tile
YAPF search; on the real machine map, with the reader/clock trains hitting real junctions, that
pathfinding share will be larger and the safe bookkeeping cut's relative win correspondingly
smaller. The genuinely big remaining lever is caching the fixed reader/clock path (the track is a
constant, so the pathfinder recomputes the same answer every time), but that is risky engine
surgery: a wrong cached decision makes a train path INCORRECTLY, which fails the "trains must still
move and path correctly" bar. It is deliberately left as the next, riskier step rather than faked
here.

### Reproduce

Rebuild as above (the per-train cut touches `src/vehicle.cpp` and `src/train_cmd.cpp`, both
recompile incrementally). Build the benchmark save by launching a dedicated server on an isolated
config (`-c C:/Users/mikea/sfcfg/openttd.cfg`, admin port 3978, NOT the live 3977), running
`start_ai LoopBench` over the admin port, polling the train count until it stabilises, then
`save loopbench`. Time both binaries with the headless command above. The build/save tooling
(`drive_build.py`, `probe.py`, `timeit.py`) and the configs live in `C:/Users/mikea/sfcfg/`.

### Independent re-measurement of the per-train cut (2026-06-21)

The per-train claim was reproduced from scratch in a separate session, on the same box, isolated by
PID (no `taskkill`, ports 3977 untouched). The OpenTTD tree was rebuilt incrementally first: the
binary came out byte-identical to the existing `openttd_fast.exe` (md5 `ab0cf3b6d5b961901d5bed2ca9bdacca`),
confirming that binary is genuinely built from the four source edits in `src/openttd.cpp`,
`src/landscape.cpp`, `src/vehicle.cpp` and `src/train_cmd.cpp`. The baseline is
`openttd_housekeeping.exe` (md5 `0135ceb0fe9f633b00ddc217a4019407`, housekeeping strip only, no
per-train cut). Both binaries were run with `OTTDOOM_LOGIC_MAP=1`; the only difference is the
per-train cut. 150000 ticks, 3 runs each, raw wall-clock seconds pasted from the shell:

| map | mode | seconds (3 runs) | avg sec | ticks/sec |
| --- | --- | --- | --- | --- |
| loopbench (smoke off) | baseline (housekeeping) | 4.278, 4.245, 4.340 | 4.288 | 34984 |
| loopbench (smoke off) | optimized (per-train cut) | 4.177, 4.196, 4.253 | 4.209 | 35639 |
| loopbench_cos (smoke on) | baseline (housekeeping) | 4.480, 4.454, 4.545 | 4.493 | 33385 |
| loopbench_cos (smoke on) | optimized (per-train cut) | 4.240, 4.204, 4.257 | 4.234 | 35430 |
| loopbench_cos (smoke on) | stock (flag off, no strips) | 5.057, 5.112, 5.103 | 5.091 | 29466 |

Startup/load measured at ticks=100 was 0.527s (opt) / 0.535s (base), so subtracting it gives the
sim-only ratio.

**Speedup of the per-train cut, same flag, only the binary differs:**
- smoke off (logic-realistic): 4.288 / 4.209 = **1.019x** wall (~1.9%), 1.019x sim-only. Modest but
  real: every optimized run beat every baseline run.
- smoke on (default cosmetics): 4.493 / 4.234 = **1.061x** wall (~5.8%), 1.068x sim-only. Larger,
  as expected, because there is real smoke/cosmetic work to remove.

For full-stack context on the smoke-on map: stock 5.091s, housekeeping 4.493s (1.13x over stock),
housekeeping + per-train cut 4.234s (1.20x over stock, 1.061x over housekeeping). The reproduced
numbers land on top of the prior session's (1.033x / 1.067x), confirming the honest "modest, real,
larger-with-cosmetics" characterisation, not a flat 3x.

**Correctness, re-proven deterministically.** With `autosave_on_exit`, the null driver writes a
bit-comparable `exit.sav` after exactly N ticks. Running `loopbench.sav` under the baseline and the
optimized binary for the same tick count (independently at N=50000 and N=75000) gave `exit.sav`
files of identical size (879209 bytes at 50000, 881479 at 75000), differing in exactly **632 bytes**
both times, first diff at offset 799347 (the vehicle region). Clustering those 632 diffs shows a
perfectly regular per-vehicle pattern: 158 clusters of 3 contiguous bytes plus 158 single bytes,
i.e. exactly 4 bytes per train (632 / 158 = 4.0), at a fixed offset within each ~197-byte vehicle
record. That is the one `uint32 motion_counter` cosmetic field the cut stops updating; every
movement field (tile, position, direction, speed, track, order state) is byte-identical. The trains
land in exactly the same places under both binaries. That the trains genuinely move was confirmed
separately: the 50000-tick exit save differs from the original in 24530 bytes and grows the file,
and the 75000-tick save is larger still. Verdict: the per-train speedup reproduces (1.02x smoke off,
1.06x smoke on) and is correctness-preserving (movement and pathing byte-identical, only the
cosmetic sound counter changes).
