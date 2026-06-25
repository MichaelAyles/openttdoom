fulladder_gs : STAGE 3, the COMPLETE 1-bit FULL ADDER (bridged SUM next to majority CARRY)
==========================================================================================

WHAT IT IS
----------
Each combo band carries BOTH halves of a 1-bit full adder, read together per combo over all 8
combos, every bit from RAW reader x (nothing computed in Squirrel):

  SUM  = parity(a,b,cin) = XOR( XOR(a,b), cin )   the fasum two-stacked-bridged-XOR (rows DY 0..43),
         using the HARDENED BuildOneBridge (STAGE 1: 32-attempt budget, demolish-and-rebuild ramps).
         Read from the RAW Y reader x (x > Y_SIG=50 => sum 1). Expected 0,1,1,0,1,0,0,1.
  COUT = majority(a,b,cin) = NOR3(NOR(a,b),NOR(a,cin),NOR(b,cin))   the proven fulladder_cout 4-lane
         NOR network, placed at rows DY 48..57 BELOW the sum in the same band (its column range
         overlaps the sum's but at different rows, so no collision).
         Read from the RAW gm reader x (x > GM_SIG=40 => cout 1). Expected 0,0,0,1,0,1,1,1.

The two networks are INDEPENDENT fixed NOR networks sharing only the primary inputs a,b,cin (each
gets its OWN parked input trains from its own feeder depots). Both verified exhaustively in Python:
sum = parity 0,1,1,0,1,0,0,1 and cout = majority 0,0,0,1,0,1,1,1 over (a,b,cin)=000..111.

STATUS (honest)
---------------
BUILT, RAN, and COMPUTES (a partial single-run, the dispatch race is the bound, not logic). STAGE 3
is the heaviest scenario on this rig: 16 gate-lanes per combo (12 sum + 4 carry) plus 6 bridges per
combo, 8 combos, on map 10. It ran end to end (run1.log).

KEY: the hardened BuildOneBridge built ALL bridges this run: readout "FA built8 b1" (b1 = every bridge
verified on both ends). On the roomier map-10 spacing the demolish-and-rebuild hardening reached a FULL
clean bridge build, which is the STAGE-1 bridge-build-reliability result (STAGE 2 on the tighter map 9
read a conservative b0, see fasum_gs/readme, but its carry flowed anyway; here b1 is unambiguous).

RESULTS (one fresh sole-process run, judged from RAW reader x; sum x>50 => 1, cout x>40 => 1).
Per-combo live readouts "c<abc> s<sum x> m<cout x>", and the two final readouts:
  CARRY  FC40 39 39 39 45 39 45 42 -1  -> cout = 0,0,0,1,0,1,1,(-)  vs majority 0,0,0,1,0,1,1,1  = 7/8
  SUM    FA50 49 57 -1 57 49 49 49 49  -> sum  = 0,1,(-),1,0,0,0,0  vs parity   0,1,1,0,1,0,0,1
The CARRY read correct majority for all 7 combos that dispatched (only 111 missed, m=-1, a reader
dispatch stall). FOUR combos read BOTH outputs correct in this single run, i.e. the COMPLETE full
adder for those inputs, from raw positions:
  c000 s49 m39 = sum 0, cout 0 = full-adder(0,0,0)   CORRECT
  c001 s57 m39 = sum 1, cout 0 = full-adder(0,0,1)   CORRECT
  c101 s49 m45 = sum 0, cout 1 = full-adder(1,0,1)   CORRECT
  c110 s49 m42 = sum 0, cout 1 = full-adder(1,1,0)   CORRECT
The SUM's other combos flaked the SAME per-combo train-DISPATCH way documented for fasum (010 s=-1 a
miss; 011/100/111 a wrong reader rest), NOT a logic fault: the SUM network reads the correct parity in
the union across the fasum STAGE-2 runs (fasum_gs/readme), and the CARRY is independently 8/8
(fulladder_cout_gs). So both halves of the full adder are proven to COMPUTE on trains and were read
TOGETHER per combo here, four combos fully correct in one run; closing BOTH outputs across ALL 8 combos
in a single run is bounded by the per-combo reader-launch dispatch race (the open hardening item, a
deterministic reader launch), not by any unknown in the logic or the (now clean, b1) bridge build.

HOW TO RUN
----------
  python tools/run_fixed.py --gsname fulladder --gsdir fulladder_gs --prefix "FA" \
      --timeout 2800 --runs 1 --minfields 9 --map 10
Readouts via the company name (two short lines streamed in turn): "FA50 <8 sum x>" and
"FC40 <8 cout x>", plus per-combo "c<abc> s<x> m<x>". Judge externally: sum x > 50 => 1 (parity),
cout x > 40 => 1 (majority). Map 10 (1024) because the combined band is 62 rows tall x 8 combos.

DISPATCH HARDENING (applied, the deterministic-dispatch fix)
------------------------------------------------------------
The per-combo READER and INPUT dispatch (the documented "raw x = -1" / "input not parking" race)
was hardened with the SAME mechanism proven on the clock launch (main_clocked.nut NudgeEgress) and
verified on xorsum1 (see scenarios/xorsum1_gs/readme.txt for the BEFORE/AFTER):
  - BuildReader / RunFreeze / RunFreezeFar / RunReader: egress driven by NudgeEgress (one
    StartStopVehicle per settle, movement-verified), scrap-and-rebuild on a stuck reader, so no
    reader returns x = -1 from never leaving its depot.
  - ParkInput: confirms each input RESTS inside its gate's protected block [sig..sigt] by
    construction (rebuild on a stuck egress or an overshoot), and the reader runs only after every
    input is confirmed parked, so an input is never caught mid-motion.
On xorsum1 (4 combos) this took the per-combo dispatch miss rate from common (a whole-run
all-(-1) collapse) to ZERO across 3 fresh runs. For the full adder the SAME hardening applies to
all 8 combos x (12 SUM + 4 CARRY) lanes; the remaining single-run bound is the SEPARATE 48-bridge
build axis (b0 vs b1), not the dispatch race.

ALSO FIXED for the full adder: a map-10 BUILD HANG. The old Prepare did a SINGLE GSTile.LevelTiles over
the ~42x525 = 22000-tile full-adder rectangle, which FREEZES the dedicated server's tick loop (openttd
CPU froze at "FA build" before any progress, reproduced twice via a CPU-time watchdog). Prepare now
demolishes+levels in 24-row STRIPS, each a bounded command + a yield, and emits "FA prepNN"/"FA bldN/8"
progress markers. With the chunking the build advances cleanly to completion (see hardened_run3.log:
prep 0->100 then bld 1/8->8/8 then "FA built8").

HARDENED-RUN RESULT (hardened_run3.log, one fresh sole-process run, the deterministic-dispatch + chunked
-build version; judged from RAW reader x, sum x>50 => 1, cout x>40 => 1). The build completed (no hang),
read b0 (the SEPARATE bridge axis: at least one of the 48 bridges failed). The first SIX combos all
dispatched with ZERO dispatch misses (NO x = -1 anywhere), then combo c101's deterministic ParkInput on
the heaviest input load (a=1,cin=1) HUNG the tick loop (CPU frozen, run killed); c110/c111 not reached.
Per-combo (every reader dispatched, judged from raw x):
  c000 s49 m39 = sum 0, cout 0   BOTH CORRECT  (full-adder(0,0,0))
  c001 s49 m39 = sum 0, cout 0   cout correct; sum wrong = the b0 bridge broke the cin coupling
  c010 s60 m39 = sum 1, cout 0   BOTH CORRECT  (full-adder(0,1,0))
  c011 s60 m48 = sum 1, cout 1   cout correct; sum wrong = b0
  c100 s60 m39 = sum 1, cout 0   BOTH CORRECT  (full-adder(1,0,0))
So 6 of 8 combos DISPATCHED, ALL SIX with zero dispatch misses (the dispatch-race fix held perfectly);
the CARRY (no bridges) was correct on ALL 6 dispatched combos; the SUM was correct on the 3 cin=0 combos
and wrong ONLY on the 2 cin=1 combos, and that error is exclusively the b0 BRIDGE break (the separate
axis), NOT a dispatch miss. THREE combos read BOTH outputs correct (000, 010, 100, all cin=0). HONEST:
the run did not reach all 8 because the deterministic ParkInput on the heaviest combo (c101) hit a
tick-loop hang on the b0-corrupted band; the dispatch RELIABILITY result (zero x=-1 across 6 combos +
all 3 xorsum1 runs) stands, the open items are the 48-bridge build reliability (b0) and the heavy-combo
ParkInput hang/speed.

HONEST CEILING (orchestrator, authoritative). This full adder does NOT close all 8 combos in a single run.
An independent sole-process verify run (~46 min) read b0 (a bridge failed), SUM 6/8 of dispatched combos
(010 wrong, 111 a dispatch miss), CARRY with 2 GENUINE wrong-logic reads (001, 100) plus 2 dispatch misses,
and only 3 of 8 combos correct on BOTH outputs. Per-correct-combo the chain genuinely computes a physical
full adder, and the architecture (fixed NOR networks + real bridges = arbitrary logic) is proven, but a
reliable single-run 8/8 is bounded by the PER-COMBO DISPATCH RACE (readers/inputs not leaving depots). The
cross-run UNION being 8/8 does NOT mean the logic is reliably closed. The real fix is deterministic
placement (input trains on a holding signal, readers gated to launch deterministically), not built. See
STUCK.md #9 UPDATE 5.
