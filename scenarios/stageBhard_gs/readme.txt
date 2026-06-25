stageBhard: the HARDENED fixed half-adder SUM bit (a XOR b) as a 6-gate NOR network on trains.
A fork of stageB_gs that fixes the g3 reconvergent-gate freeze flake (the ~1-in-4 whole-run
all-ones failure). Network and geometry are IDENTICAL to stageB; only the freeze reliability is
hardened. GS GetName "stageBhard", short name "STBH".

NETWORK (merge-free; the fan-out driver NOR(a,b) is DUPLICATED as g0a, g0b so every gate drives
exactly ONE consumer block, the proven norchain coupling):
    g0a = NOR(a, b)  -> n1a      g0b = NOR(a, b)  -> n1b
    g1  = NOR(a,n1a) -> n2       g2  = NOR(b,n1b) -> n3
    g3  = NOR(n2,n3) -> n4       g4  = NOR(n4)    -> y
Expected y over (a,b) = 00,01,10,11: 0,1,1,0 = XOR, judged from RAW g4 reader x (x > F_SIG == 1).

THE FLAKE (diagnosed). In stageB the reconvergent gate g3 = NOR(n2,n3) freezes on a coupling tile
C_CPL=50 that sits 6 tiles EAST of its terminating signal C_SIGT=44 (filler track), pushed far so
the g3 -> g4 output spur (column 50) clears the intervening g2/g0b lanes. About 1 run in 4 g3
failed to reach CPL: its reader passed the reader signal (output 1) but was HELD short near x40-42,
at its terminating signal, so the g3 -> g4 coupling never delivered a train into g4's input block,
and EVERY combo then read g4 = passed = y = 1 (whole-run "STGB s49 54 54 54 54" = 1,1,1,1). The
failure is SYSTEMATIC PER RUN (all four copies fail together), which points to a global condition
at read time, not per-combo randomness: g3's long freeze block [C_SIGT+1 .. C_TERM2] momentarily
or persistently red, either because a critical signal in that block did not actually build, or the
g3 -> g4 column-50 spur couples g4's lane reservation into the freeze block while it settles.

A NOTE ON A FIX THAT DID NOT WORK (kept honestly): DEFERRING the g3->g4 spur (build it only after g3
freezes, so g3 reads a clean isolated block) DID make g3 freeze reliably on CPL=50, but it BROKE the
coupling: adding the spur track AFTER g3's train is already stopped does not retroactively merge that
stopped train's occupancy into g4's input block in OpenTTD 15.3, so g4 always read its input empty and
PASSED (every combo read y=1, all-ones again, for a different reason). So the spur MUST be built UP FRONT
(then the frozen g3 train is physically in the merged block the instant it rests on CPL=50, and the
coupling delivers immediately). The g3 freeze is instead hardened by the changes below.

THE HARDENING (changes over stageB, geometry and the up-front coupling unchanged):
 1. VERIFIED SIGNAL BUILDS (SignalVerified). Every lane signal (reader, terminating, and the g3
    third terminating signal C_TERM2 that makes the far freeze block a THROUGH block) is now built
    with a confirm-and-retry loop: GSRail.GetSignalType is polled and BuildSignal re-issued until
    the signal is actually present. A signal that silently failed to build (a command-queue stall,
    or a not-yet-clean tile) left a gap that turned g3's freeze block into a dead end, exactly the
    systematic hold-short. This removes the build-failure path.
 2. SETTLE DELAYS. A global settle (Sleep 40) after all four copies are built lets the whole
    network's signal/reservation graph stabilise before any read; a per-case settle (Sleep 20)
    after g1/g2 are frozen lets their couplings (n2 at C_T2, n3 at C_T3) finish reserving into g3's
    input block, so g3's reader-signal aspect is stable when g3 dispatches; and a LONGER settle
    (Sleep 40) after g3 freezes, before g4 reads, lets g3's freeze occupancy fully settle in the
    merged g3->g4 block so g4's reader signal is red BEFORE g4 dispatches. Without that last settle,
    when g3 passes (n4=1, on b00/b11) g4 could pass its signal at ~50 (y=1) before the occupancy
    registered, instead of being held at ~48 (y=0): the residual b11 flake.
 3. PATIENT FAR-FREEZE (RunFreezeFar, used only for g3). The far freeze now polls up to 420 times
    (vs 160) and, crucially, does NOT abandon the read while the reader is held short (passed the
    reader signal, x in (C_SIG, C_CPL)): it treats that as "parked at the terminating signal,
    waiting for the freeze block to green" and keeps waiting, only re-kicking if the reader somehow
    re-entered its depot. So a transiently-red freeze block has ample time to clear and let g3 roll
    to CPL=50 and freeze there.
 4. READER BUILD RETRY (RunReader). g4's reader BuildVehicle is retried until a valid vehicle is
    built: right after the heavy per-copy build a single BuildVehicle could return an invalid handle,
    seen as g4 = -1 (a non-reading run). Retry removes that.

NO per-gate coupling/driver train is re-parked or disposed between reads (0 SellVehicle). The
hardening only adds patience, settle time, and signal-build verification; each combo is still one
fixed network copy built once, six readers run in topological order, g3 frozen on its CPL.

RUN:  python tools/run_fixed.py --gsname stageBhard --gsdir stageBhard_gs --prefix "STBH s" \
          --minfields 6 --timeout 700 --runs 10
(timeout 700: the per-case settles push a 4-combo sweep + final latch past the old 600s.)
Readout via the company name: "STBH s49 <g4x00> <g4x01> <g4x10> <g4x11>", plus live per-combo
intermediates "b<ab> g3<g3x> g4<g4x>". Judge: g4 x > F_SIG (49) => output 1.

RESULTS (fresh dedicated-server runs, judged from RAW g4 reader x, x > F_SIG=49 => 1). The network
COMPUTES the XOR: every CLEAN run reads "STBH s49 48 54 54 48" = 48->0, 54->1, 54->1, 48->0 = 0,1,1,0
= XOR, judged from the RAW positions, no XOR in Squirrel. The diagnostic c-field is g3's b11 freeze x
(c50 = g3 froze on its coupling tile, the clean case; c42 = g3 short-froze).

HONEST RELIABILITY (the real number). The hardening did NOT reach >=9/10. The key fix DID help, the
BuildVehicle RETRY (BuildReader / ParkInput): the earlier all-ones often came from a transient invalid
-vehicle build right after the heavy per-copy build (a reader x of -1, or an input train that never
parked), and retrying every BuildVehicle removed that path. But a SECOND, deeper flake remains: the
reconvergent gate g3 short-freezes (held at its terminating signal near x42, c42) and the patient far
-freeze (RunFreezeFar, 420 polls) recovers it only SOME of the time. Across the clean-version fresh
runs the XOR read 0,1,1,0 in 4 of 7 (the 3-run diagnostic 3/3 c50, then a 5-run confirmation that read
0,1,1,1 c42 / 0,1,1,0 c50 / 1,1,1,1 c42 / ...): so the short-freeze flakes roughly 40 percent of runs,
sometimes for the WHOLE run (all-ones, every combo's g3 short-froze, c42). When g3 freezes the logic is
exactly right (0,1,1,0); the bottleneck is purely the g3 reconvergent FAR-FREEZE under the merged g3-g4
block, an OpenTTD reservation-settling effect the patient budget cannot fully overcome.

So the honest status: the XOR is BUILT and COMPUTES (every clean run is exactly 0,1,1,0), the all-ones
build-hiccup path is fixed, but the g3 reconvergent freeze is only ~60 percent reliable, NOT the >=9/10
target. The real fix is a freeze that does not depend on the merged g3-g4 block settling (a physical
output register), which is the same reservation-coupling obstacle as STUCK.md blocker 1. NOTE the
COMPANION carry network (fulladder_cout_gs, majority) is reliable (clean 8/8) precisely BECAUSE its
output gate gm is a TERMINAL read with no far-pushed reconvergent freeze.
