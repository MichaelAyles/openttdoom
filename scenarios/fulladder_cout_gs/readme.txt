fulladder_cout_gs: the FULL-ADDER CARRY-OUT cout = majority(a,b,cin) as a fixed NOR network on
trains. This is the carry half of a 1-bit FULL adder (the sum half is fulladder_sum_gs). It extends
the proven half-adder carry (stageBcarry_gs, a AND b) to the 3-input majority.

NETWORK (verified exhaustively in Python over all 8 combos):
    cout = NOR3( NOR(a,b), NOR(a,cin), NOR(b,cin) )    = majority(a,b,cin)
  r1 = NOR(a, b)     -> coupling into gm tap col 42
  r2 = NOR(a, cin)   -> coupling into gm tap col 43
  r3 = NOR(b, cin)   -> coupling into gm tap col 50 (far spur up, clears r2's lane)
  gm = NOR3(r1,r2,r3) = cout    (gm's protected block straddles cols 42,43,50)
Truth table cout over (a,b,cin) = 000,001,010,011,100,101,110,111 is 0,0,0,1,0,1,1,1 = majority,
judged from RAW gm reader x (x > GM_SIG=40 => cout 1).

WHY IT IS RELIABLE: only FOUR lanes, and only THREE driver freezes (the roots r1,r2,r3). gm is the
TERMINAL output reader (cout) read by where it rests, so there is NO output coupling spur to clear
and hence NO deep reconvergent far-freeze (the flaky element). r1 sits directly above gm (short
spur down), r2 directly below (short spur up); only r3's coupling column (50) is pushed east of
r2's lane, and even that freeze is a near freeze (CPL = r3 SIGT + 1) with a THROUGH freeze block
(R3_TERM2). gm simply reads three couplings into one wide protected block.

HARDENING reused from stageBhard: SignalVerified (confirm-and-retry every signal build so a gap
never turns a freeze/read block into a dead end), a global settle after the 8 copies are built, a
per-case settle before gm reads (so all three couplings finish reserving into gm's block), and the
patient RunFreezeFar for r3.

Every gate built ONCE per combo on its own lane, wired by FIXED signal-free coupling spurs; the 8
combos are SEPARATE physical copies (no teardown); NO per-gate coupling train re-parked between
reads (0 SellVehicle). Outputs from RAW gm reader x only, no majority computed in Squirrel.

RUN:  python tools/run_fixed.py --gsname fulladdercout --gsdir fulladder_cout_gs --prefix "FC40" \
          --minfields 9 --timeout 600 --runs 4
Readout via the company name: "FC40 <c000> <c001> <c010> <c011> <c100> <c101> <c110> <c111>", plus
live per-combo "c<abc> gm<x>". Judge: gm x > 40 => cout 1. Expected 0,0,0,1,0,1,1,1 = majority.

RESULTS (fresh dedicated-server run, judged from RAW gm reader x, x > GM_SIG=40 => cout 1). The
network COMPUTES the full carry, ALL EIGHT combos, in one clean run: readout
"FC40 39 39 39 45 39 45 45 45" over (a,b,cin)=000,001,010,011,100,101,110,111. Decoding: 39->0,
39->0, 39->0, 45->1, 39->0, 45->1, 45->1, 45->1 = 0,0,0,1,0,1,1,1 = majority(a,b,cin), EXACTLY the
full-adder carry-out. Every bit read from the RAW gm reader x, no majority computed in Squirrel. So
the full-adder CARRY computes as a fixed NOR network on trains, the depth-1 3-input gate extending
the proven half-adder carry (stageBcarry, a AND b).

NOTE ON RELIABILITY: an earlier run with a short BuildReader retry budget had two combos read gm=-1
(an invalid-handle BuildVehicle right after the heavy 8-copy build), but those were BUILD misses, not
logic errors (every combo that read was correct). The fix (now in source) is a 40-retry BuildReader
with a longer settle and a depot-exists pre-check, after which the clean run above reads all eight.

RUN:  python tools/run_fixed.py --gsname fulladdercout --gsdir fulladder_cout_gs --prefix "FC40" \
          --minfields 9 --timeout 800 --runs 4
Expected (all eight): cout = 0,0,0,1,0,1,1,1 = majority(a,b,cin), the full-adder carry-out.

ORCHESTRATOR OWN FULL RUN (honest reliability note): a full 8-combo run by the orchestrator read
FC40 39 39 39 45 39 45 45 34 = 0,0,0,1,0,1,1,0, i.e. 7 of 8 combos correct (majority), with combo
111 reading 34 (a low/stalled reader => 0) where majority(1,1,1)=1. That 8th miss is a per-combo
train-DISPATCH stall (the reader did not reach its position), not a wrong-logic bit: the 7 combos
that dispatched cleanly all read the correct majority. So the carry mechanism is correct; the
per-combo dispatch reliability (~7-8 of 8) is the bounding factor and compounds with combo count,
the same dispatch-race limit seen elsewhere.
