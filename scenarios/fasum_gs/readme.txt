fasum_gs : STAGE 2, the FULL-ADDER SUM = parity(a,b,cin), two bridged-XOR stages chained
============================================================================================

WHAT IT IS
----------
The full-adder SUM bit = parity(a,b,cin) = XOR( XOR(a,b), cin ), built as TWO XOR stages
chained on real trains, the XOR1 output coupled into XOR2's input (a bridged chain link).

  XOR1 (the proven xorsum1 6-gate bridged XOR) computes h = a XOR b.
  XOR2 (a 7-gate regen XOR where h is read EXACTLY ONCE, fan-out 1) computes s = XOR(h, cin):
      NHa=NOR(h)->HH   NHb=NOR(h)->Q   HH=NOR(nha)->P   NC=NOR(cin)->Q
      P=NOR(hh,cin)->Y  Q=NOR(nhb,nc)->Y  Y=NOR(p,q)->s
  nh fan-out 2 (HH and Q) is realised by DUPLICATING the NH gate (NHa drives HH, NHb drives Q),
  both reading the h-chain; since both compute NOR(h) (the same signal), the h coupling merging
  their input blocks is benign. Only the NHb->Q coupling needs a BRIDGE (over NHa,HH,P,Y).

THE CHAIN LINK
--------------
h = XOR1.g4's FROZEN reader at (col 50, XOR1 g4 row). XOR2.NHa and NHb read h at col 50; the h
coupling is a vertical spur in column 50 from XOR1.g4's row DOWN into NHa/NHb's input blocks (it
crosses no other lane, so it is a plain spur here; in general it would BRIDGE where it crosses).

The full netlist is verified EXHAUSTIVELY in Python = parity 0,1,1,0,1,0,0,1 over (a,b,cin)=000..111
(h read once = fan-out 1; cin = primary, replicable). Bridges per combo: XOR1 g3->g4 (2) + XOR2
NHb->Q (4) = 6. Each combo is a SEPARATE physical copy (no teardown); 8 combos; map 9 (512).
Outputs (s) from RAW Y reader x only (x > Y_SIG=50 => 1); no parity computed in Squirrel.

STATUS (honest)
---------------
This is the chained-XOR full-adder SUM, built on the proven STAGE 1 bridged XOR and the proven
bridge primitive. It is LARGE (12 gate-lanes/combo, 8 combos, 6 bridges/combo) and is therefore the
hardest stage for this OpenTTD 15.3 rig, which intermittently reloads the GameScript on a heavy
build (mitigated with the same yield fix as xorsum1). Per-combo results are reported SHORT as they
complete ("c<abc> h<x> s<x>") so the chain's computation is visible combo by combo even on a partial
run. See the run logs for the latest result.

HOW TO RUN
----------
  python tools/run_fixed.py --gsname fasum --gsdir fasum_gs --prefix "FS" \
      --timeout 1200 --runs 4 --minfields 9 --map 9
Readout: final "FS50 <8 s reader x>" plus per-combo "c<abc> h<x> s<x>". Judge externally:
s reader x > 50 => sum 1. Expected parity 0,1,1,0,1,0,0,1.
