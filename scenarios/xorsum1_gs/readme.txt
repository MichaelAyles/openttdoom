xorsum1_gs : STAGE 1, the half-adder SUM (a XOR b) with the reconvergent output coupling
             routed as a BRIDGE instead of stageB's flaky far-push (the reliability fix)
=============================================================================================

WHAT IT PROVES
--------------
The SAME 6-gate NOR XOR network as stageB_gs (the proven half-adder SUM), but the ONE
reconvergent output coupling (g3 -> g4) is routed as a length-3 rail BRIDGE over the two
intervening lanes (g2, g0b) instead of being far-pushed east into a long merged block.

stageB / stageBhard reach the right answer 0,1,1,0 = XOR but only ~57% of runs, because g3's
coupling tile was pushed ~6 tiles east of its terminating signal (filler track) to clear the
intervening lanes, putting g3's freeze block in a long merged region that only settled about
half the time. Here g3 freezes CLOSE (one tile past its terminating signal) and the g3 -> g4
spur BRIDGES over g2's and g0b's lanes (the bridgeprobe / xorbridge primitive). No far-push, no
flaky merged block: the bridge fixes BOTH planarity (it always did) AND reliability.

NETWORK (identical to stageB, merge-free; fan-out driver NOR(a,b) duplicated as g0a,g0b):
    g0a=NOR(a,b)->n1a  g0b=NOR(a,b)->n1b  g1=NOR(a,n1a)->n2  g2=NOR(b,n1b)->n3
    g3=NOR(n2,n3)->n4  g4=NOR(n4)->y       y = a XOR b
Truth table y over (a,b)=00,01,10,11 is 0,1,1,0 = XOR, judged from RAW g4 reader x (x>F_SIG=44 => 1).

THE BRIDGE (the change vs stageB)
---------------------------------
g3 -> g4 is a vertical coupling spur in column C_CPL=45 from g3's row down to g4's row. It crosses
g2's lane (DY 9) and g0b's lane (DY 13). Each crossing is a length-3 N-S BRIDGE over the lane tile
(ramps empty of rail, the under-tile carries the E-W lane rail, verify-under-rail + retry, the
proven recipe). Column 45 lies strictly inside g2's and g0b's THROUGH blocks [CPL..TERM2] so a
LEVEL crossing there would short the lane (the bridge is load-bearing). g3 freezes on C_CPL=45,
one tile past its terminating signal C_SIGT=44 (C_TERM2=46 makes the freeze block a through block).

RESULT (judged from RAW g4 reader x; x > 44 => 1)
-------------------------------------------------
Per-combo intermediates (verified across fresh runs): c00 g3=45/g4=43 -> y=0; c01 g3=40/g4=56 ->
y=1; c10 g3=40/g4=56 -> y=1; c11 g3=45/g4=43 -> y=0. So 0,1,1,0 = XOR, with all bridges built (b1).
The per-combo logic is verified: e.g. c00 (a=0,b=0) g3 PASSES (frozen 45, n4=1) so g4 is held
(43 <= 44, y=0); c01 g3 HELD (40, n4=0) so g4 PASSES (56 > 44, y=1).

RELIABILITY CAVEAT (honest)
---------------------------
The bridged XOR computes correctly EVERY time it completes a combo (the bridge fix works), but
this OpenTTD 15.3 rig intermittently RELOADS the GameScript mid-run (the company name resets to
"XS1 build" and Start() re-runs). It happens at varying combos (seen at c01 and c11). The dominant
cause was the heavy build flooding the command queue in one GS step; the fix here is to YIELD
(GSController.Sleep) inside Prepare's demolish loop, after each lane build, and between copies (the
same yield fix STATUS.md notes for SC2). Per-combo results are reported SHORT as they complete (the
runner records every distinct company name), so even a late reload does not lose the combos that
DID complete. See the run logs for the latest reliability count.

RECONVERGENT-FREEZE FIX (the g3 -> g4 coupling, the last logic-reliability blocker)
-----------------------------------------------------------------------------------
After the dispatch race was fixed (zero x = -1), a SEPARATE logic axis remained: the bridged XOR
read the WRONG value about half the time, ALWAYS on c00 (and sometimes c01), the reconvergent
gate g3 -> g4. Diagnosed precisely from the per-combo g3 freeze positions in the run logs:

  c00 should read g3=45 (PASSED, frozen ON the coupling tile C_CPL=45) so g4 is HELD at 43 (y=0).
  The flake read g3 still passed but g4 wrongly PASSED at 56 (y=1), i.e. g3's occupancy did NOT
  reach g4's input block through the bridge.

ROOT CAUSE (geometry). g3's coupling block was the NARROW 2 tiles [C_CPL..C_TERM2] = [45..46]
(C_SIGT=44 on the west, C_TERM2=46 on the east). The g3 -> g4 spur drops at column 45 and the WHOLE
spur (top corner on g3's lane, both bridges, g4's input tap) is ONE signal block, so a passing g3
frozen anywhere in [45..46] occupies g4's input. But the freeze fired an ASYNC StartStopVehicle at
fx >= 45 and the train DRIFTED a tile or two before physically stopping; on a 2-tile window that
drift could carry g3 PAST C_TERM2=46 into the [46..52] block, which is DISCONNECTED from the spur.
Then g4's input read empty and g4 wrongly passed. The overshoot landed g3 "a few tiles off the
coupling tile", exactly the reported symptom.

THE FIX (two parts, both deterministic by construction, reusing the norchain / bridgeprobe recipe):
  (i) WIDEN the coupling block. C_TERM2 moved 46 -> 50, so g3's coupling block is now [45..50], a
      6-tile through block all connected to the spur at column 45. Any rest in [45..49] occupies the
      spur and therefore g4's input through the bridge, so the freeze drift is absorbed. Nothing else
      uses g3's row east of 44, so the widen is collision-free (C_EAST moved 52 -> 54 to keep the east
      depot past the wider block).
  (ii) A DEDICATED g3 freeze (RunG3Freeze) that PINS and VERIFIES the landing. When g3 passes it is
      driven to rest at or past C_CPL=45 and strictly WEST of C_TERM2 (re-nudged off the ambiguous
      C_SIGT=44 terminating-signal tile if it stalls there), and the rest is CONFIRMED inside
      [C_CPL..C_TERM2) on-row, or diverted into the spur off-row, before g4 is dispatched. A genuinely
      HELD g3 (input occupied) rests at C_SIG-1 and is returned as-is (output 0). So g4 never reads
      against an undelivered coupling.

BEFORE vs AFTER (logic-clean rate, fresh sole-process runs reading 0,1,1,0 with b1, zero x = -1):
  BEFORE (orchestrator's 5 runs on the old narrow window): 2/5 logic-clean; 3 runs had a wrong combo,
    always c00/c01 (c00 read x=56 where it should be 43, the g3 overshoot above).
  AFTER (this fix, 5 completed fresh runs + a 6th cut off mid-flight after reading c00/c01 correctly):
    5/5 logic-clean, every run "XS1 s44 43 56 56 43 b1" = 0,1,1,0, all b1, zero x = -1. Per-combo
    diagnostics were stable every run: c00 g3=45 / g4=43 (g3 pinned ON the coupling tile, g4 held);
    c01 g3=40 (or 36) / g4=56; c10 g3=40 / g4=56; c11 g3=45 / g4=43. The c00 g3 freeze now lands on
    45 EVERY run instead of overshooting, which is the whole fix.

DISPATCH HARDENING (Stage 1 + Stage 2, the deterministic-dispatch fix)
----------------------------------------------------------------------
The per-combo READERS and INPUTS used to flake: a reader that never left its depot read raw
x = -1, and an input train caught mid-motion on its single tap tile overshot to the east depot
(wrongly absent). Both are the documented dispatch race. Two fixes, reusing the proven
clock-launch egress hardening (main_clocked.nut NudgeEgress):

  Stage 1 (reader/input egress): BuildReader and ParkInput now drive egress with NudgeEgress, which
  fires EXACTLY ONE StartStopVehicle per settle and verifies the train left its depot tile before
  returning. The old tight poll re-fired the async (queued) StartStop toggle while a prior one was
  still in flight, double-toggling the train back to a stop (~1 in 3 fresh egresses stuck). A
  reader that will not leave is scrapped and rebuilt (up to a budget), so no reader returns x = -1.

  Stage 2 (deterministic input placement): ParkInput now CONFIRMS the input came to rest inside its
  gate's protected block [sig..sigt] by construction, and rebuilds on a stuck egress or an
  overshoot past sigt. The reader is dispatched only after every input is confirmed parked, so an
  input is never caught mid-motion. The reader read needs only block occupancy (presence anywhere
  in [sig..sigt]), so resting in-block is exactly correct.

BEFORE vs AFTER (g4 reader raw x, judged externally; x = -1 == a dispatch MISS).
  BEFORE (unhardened, 3 fresh runs x 4 combos = 12 dispatches): one run read
    "XS1 s44 -1 -1 -1 -1" = ALL FOUR g4 readers missed (x = -1), plus the g3 readers in that run
    also -1; the other two runs read all four. So >= 4/12 g4 misses, plus a whole-run collapse.
  AFTER (hardened, 3 fresh runs x 4 combos = 12 dispatches): ZERO x = -1 across every readout.
    run1 "XS1 s44 43 56 56 43 b1" = 0,1,1,0 = XOR, clean.
    run2 "XS1 s44 43 56 56 43 b1" = 0,1,1,0 = XOR, clean.
    run3 "XS1 s44 43 56 56 56 b0" = 0,1,1,1: ZERO dispatch misses, but b0 (a BRIDGE failed to
      build, the SEPARATE bridge-build axis), which broke the g3->g4 coupling for c11 so g4 read
      empty (56) and c11 read 1 instead of 0. NOT a dispatch miss.
So the dispatch race went from common (a whole-run all-(-1) collapse) to NIL (0 misses in 12). The
one wrong AFTER output is the independent bridge-build flake (b0), unchanged by this fix. HONEST
COST: deterministic ParkInput trades speed for certainty (the a=1,b=1 combo's confirm-and-rebuild
can take a few minutes), so use a generous --timeout.

HOW TO RUN
----------
  python tools/run_fixed.py --gsname xorsum1 --gsdir xorsum1_gs --prefix "XS1" \
      --timeout 800 --runs 3 --minfields 6 --map 9
Readout: final "XS1 s44 <y00> <y01> <y10> <y11> b<all bridges built>", plus per-combo
"c<ab> g3<x>/g4<x>". Judge externally: g4 x > 44 => XOR 1. Expected 0,1,1,0. A reader/input that
fails to dispatch would read x = -1; the hardened dispatch produces none.

HONEST RATE (orchestrator, authoritative; corrects any "5/5 fixed" above). The geometry fix (widened g3
coupling block + RunG3Freeze pin) fixed the reconvergent OVERSHOOT drift and took the bridged XOR from
~40% to ~80% logic-clean (build 6/8, adversarial verify 4/5, orchestrator 3/3 fresh sole-process runs =
~13/16 reading 0,1,1,0, b1, zero x=-1). It is NOT closed: the adversarial verify caught a residual g3
reader-EGRESS UNDERSHOOT stall (g3 stalls at x=36, never reaches the coupling block, indistinguishable
from a held output-0, so c00 fails ~1/5). Fix = the rebuild-on-stall budget ParkInput has, not yet built.
See STUCK.md #9 UPDATE 7.
