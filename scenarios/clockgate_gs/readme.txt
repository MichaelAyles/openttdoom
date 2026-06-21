clockgate_gs: a CLOCK train, LIVE gate re-evaluation, and clock-synced sampling
==============================================================================

This is the last research-flavoured de-risk for the openttdoom clocked machine. It
builds on the verified single-gate primitive (scenarios/norgate_gs) and the verified
two-gate composition (scenarios/norchain_gs), and pushes toward a synchronous,
clocked gate. There are three sub-goals, in order of difficulty.

Everything is built and observed entirely from a GameScript (Squirrel) on a dedicated
server, driven headlessly through the admin port. Results are read through the COMPANY
NAME (rcon companies), because GSLog does not relay reliably to the admin console here.
That is THE proven readout channel for this project.

How to run (headless, bundled binary)
--------------------------------------
1. Copy this folder to the OpenTTD game dir:
     ~/OneDrive/Documents/OpenTTD/game/clockgate_gs/
   It contains info.nut (GetName "clockgate", NO space) and one of the main_*.nut
   variants copied to main.nut (see "Variants" below).
2. In openttd.cfg, set the [game_scripts] first entry to:  clockgate =
   Have a flat, water-free map (terrain_type 0, no rivers, no water borders); the GS
   demolishes + LevelTiles its build rectangle first regardless.
   secrets.cfg admin_password set, openttd.cfg allow_insecure_admin_login = true.
3. Start a dedicated server from the binary dir:
     ./openttd.exe -D -d script=1
4. Found a company for the deity GS to build as, then poll the readout:
     python tools/ottd_admin.py rcon "start_ai"
     python tools/ottd_admin.py rcon "companies"     (repeat every few seconds)

Variants (each is a self-contained main_*.nut; copy the one you want to main.nut)
--------------------------------------------------------------------------------
  main_clock.nut   SUB-GOAL 1: the clock train on a closed loop.
  main_reeval.nut  SUB-GOAL 2: live re-evaluation of one NOT gate on the same tiles.
  main_sync.nut    SUB-GOAL 3: clock-released sampling (the synchronous gate attempt).
  main.nut         a copy of whichever variant was last run/verified.

The info.nut CreateInstance name must match the variant's class:
  ClockGateMain (main_clock), ReevalMain (main_reeval), SyncMain (main_sync).

--------------------------------------------------------------------------------
SUB-GOAL 1: the clock train (VERIFIED)
--------------------------------------------------------------------------------
main_clock.nut builds a small rectangular rail loop (corners are single curve track
pieces, the same constants as the norchain coupling spur) with a depot dropped onto
the top run. A single train is spawned and given two cycling destination orders (the
bottom-right corner, then the top-left corner), so its order list repeats and it
circles the ring forever. One lap is one clock edge.

The clock is PROVEN by sampling the train's tile (x,y) at fixed wall-clock intervals
(GSController.Sleep(20) per sample) and streaming a window of successive samples into
the company name "CK<idx> ... x.y", read with rcon companies. Across many samples the
position sweeps the loop and the same positions recur with a repeating period.

Measured (a continuous idx -> live-position trace, see the run log): the train sweeps
the depot (33,29) -> top run east -> right side down -> bottom run west -> left side up
-> back to (33,29), every lap. Taking the depot tile (33,29) as the clock-edge
reference, the departure-edge idx across six consecutive laps were
  107, 133, 160, 186, 213, 238
giving lap periods of 26, 27, 26, 27, 25 sample intervals (one interval = 20 ticks),
i.e. a stable period of ~26 intervals (~520 ticks) with +/-1 jitter that is purely the
discrete-polling alias. Six laps, tight repeating period => the position genuinely
cycles. clock_verified = true.

--------------------------------------------------------------------------------
SUB-GOAL 2: live re-evaluation on the SAME tiles (VERIFIED)
--------------------------------------------------------------------------------
main_reeval.nut builds ONE NOT gate (the norgate primitive: a straight lane with a
reader signal protecting an input block terminated by a second signal, plus an input
feeder depot) and re-evaluates it three times while it stays built, changing only the
input:
  read A: input ABSENT  -> reader PASSES -> final x at the east end   == NOT(0)=1
  poke:   ADD an input train on the tap (the gate is NOT rebuilt)
  read B: input PRESENT -> reader HELD at the signal                  == NOT(1)=0
  unpoke: REMOVE the input train (the gate is NOT rebuilt)
  read C: input ABSENT  -> reader PASSES -> final x at the east end   == NOT(0)=1

Readout: "REEVAL sNN xa xb xc". Judge from the RAW positions: xa>NN and xc>NN (passed),
xb<=NN (held).

Two teardown facts were the crux, both found empirically here and documented in the
source:
  - A normal one-way block signal BLOCKS the return trip (its back is solid), so a
    single reader cannot ping-pong back west through the gate. Each read uses a FRESH
    eastbound reader from the west depot, on a simple lane (no coupled junction, so the
    norchain teardown hang does not apply).
  - GSVehicle.SellVehicle only works on a vehicle stopped IN A DEPOT, so a reader HELD
    at the signal cannot be sold in place (it strands and jams the lane). A held reader
    is freed by REMOVING the input first (its block empties, the signal greens); it then
    rolls into the east depot on its standing order and is sold there cleanly. So read
    B's reader is disposed only AFTER the unpoke.

reeval_verified = true (the same gate's output followed the input across live changes).

--------------------------------------------------------------------------------
SUB-GOAL 3: clock-synchronised sampling (PARTIAL: clock-released, GS-mediated)
--------------------------------------------------------------------------------
main_sync.nut combines the verified clock loop and the verified NOT gate. The clock
train is the real periodic source; the GS detects a clock EDGE by watching the clock
train ENTER the top run of its loop (WaitClockEdge, a rising y==LY0 edge, robust to the
poll phase), and only then releases one gate sample. So each sample is gated by the
clock train's passage, NOT by a free-running timer. A known input schedule is driven
and the gate output is read once per edge.

Verified run (input schedule 0 0 1 1 0 0, read via the company name per edge):
  e0 in0 p6  x49 o1 [1]        e1 in0 p11  x49 o1 [11]
  e2 in1 p102 x45 o0 [110]     e3 in1 p88  x45 o0 [1100]
  e4 in0 p104 x49 o1 [11001]   e5 in0 p11  x49 o1 [110011]
giving output 1 1 0 0 1 1 == NOT of the input 0 0 1 1 0 0 at each edge, sampled once
per clock edge. The p values are the per-edge waits for the clock train to reach the top
run; every one is small (6,11,102,88,104,11), NOT the 300 timeout, so each sample was
released by the clock train's passage, not by a free timer. A separate run independently
confirmed all six edges detecting real clock edges (k0..k5 waits 72,11,27,57,105,11) with
the clock alive on the top run (cy60) at sample time. So the gate output tracks the live
input, edge by edge, on the same physical gate tiles, released by the clock.

HONEST LIMITS (why this is PARTIAL).
 1. The release is MEDIATED BY THE GAMESCRIPT: the GS polls the clock train's position
    (WaitClockEdge) and then dispatches the reader. It is NOT a pure track-signal
    interlock where a clock-driven signal physically releases a waiting reader with zero
    GS in the loop. Building that pure interlock (a clock pulse opening a reader's release
    signal, a latch holding the output for a full period) is the remaining hard piece.
 2. The one-edge register latency of scenarios/gate_model.py is approximated by the
    schedule discipline (the input is changed at an edge boundary and observed at the next
    sample), not realised as a physical output register.
 3. Run-to-run reliability is imperfect. The clean six-edge sequence above reproduced in
    two runs, but other runs stalled: the clock train's two-order cycle occasionally parks
    it, and the per-edge reader disposal can lag and jam the gate lane, after which a later
    edge cannot complete its sample. DrainReaders mitigates the jam; the clock stall does
    not yet have a robust fix here. So a SINGLE run does not always carry all six edges to
    the consolidated readout, even though the synchronisation itself is proven.
So sub-goal 3 demonstrates clock-released, clock-cadenced re-evaluation whose output
tracks a known input schedule, but not the full hardware interlock, and not yet reliably
in one shot. See ../../STUCK.md and the run report.

Honest scope
------------
Verified in game (raw observations, not the GS's own pass/fail): the clock train cycles
with a stable period (sub-goal 1) and the NOT gate re-evaluates on the same tiles across
live input changes (sub-goal 2). Sub-goal 3's status is reported honestly in the run
report and the main_sync.nut header. Wiring the output train-presence into the
framebuffer signals, and folding this geometry into the place-and-route emitter, remain
future work (see ../../STUCK.md).
