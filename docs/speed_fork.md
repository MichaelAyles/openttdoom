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
