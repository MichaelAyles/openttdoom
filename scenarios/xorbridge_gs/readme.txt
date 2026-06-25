xorbridge_gs : STAGE 2, the bridge crossing composing into real reconvergent logic
====================================================================================

WHAT IT PROVES
--------------
The bridge primitive (proven in isolation by bridgeprobe_gs) is used to build a
RECONVERGENT NOR network whose coupling is deliberately NON-PLANAR: one driver's
coupling spur must CROSS an intervening root's reader lane. That crossing is routed as a
BRIDGE, so the network computes correctly where a flat-lane (level-crossing) layout would
short. The network computes the half-adder CARRY = a AND b:

    g0 = NOR(a) -> na        (NOT a; root)
    g1 = NOR(b) -> nb        (NOT b; root)
    g2 = NOR(na, nb) = AND(a,b)   (reconvergence; output)

stageBcarry_gs places g2 BETWEEN its two drivers (planar, no crossing). HERE g2 is BELOW
both roots, so g0's coupling spur to g2 runs from g0's row PAST g1's row down to g2, and
must CROSS g1's reader lane. The crossing is a length-3 N-S BRIDGE over g1's lane tile
(inside g1's protected block G1_SIG..G1_SIGT). g0 stays coupled to g2 through the bridge;
g1's lane stays a separate block under the bridge.

RESULT (judged from RAW g2 reader x; x > G2_SIG=38 => AND 1)
-----------------------------------------------------------
Single fresh run: "XB s38 37 37 37 49 b1"
  c00 x37 -> 0     c01 x37 -> 0     c10 x37 -> 0     c11 x49 -> 1
Truth table 0,0,0,1 = AND(a,b), with all bridges built (b1). Intermediates confirm the
logic, e.g. c10 (a=1,b=0): g0 held x35 (na=0 not delivered), g1 frozen x42 (nb=1 coupled),
g2 held x37 (nb present -> AND 0).

This is the bridge crossing carrying a real reconvergent coupling: the non-planar
g0 -> g2 spur passes OVER g1's lane and the AND still computes across all four combos.

SCALING NOTE (how far this goes toward the full-adder SUM)
---------------------------------------------------------
The full-adder SUM = parity(a,b,cin) is non-monotone and needs depth >= 2 reconvergence;
the compact flat parity netlist needs ~28 unavoidable spur crossings (STUCK.md #9). Each
such crossing is exactly the primitive proven here: a coupling spur bridging OVER an
intervening lane. xorbridge demonstrates ONE such bridged reconvergent coupling computing
correctly. A full parity sum stacks many of these (the two-stacked-XOR design in STUCK.md
#9, each half-sum coupling bridged over the intervening lanes); building all ~28 in one
copy x 8 combos is the remaining scale work. The load-bearing primitive (a bridge crossing
that keeps two nets isolated) is proven; replicating it ~28x is mechanical but was beyond
this run's build/verify time budget.

HOW TO RUN
----------
  python tools/run_fixed.py --gsname xorbridge --gsdir xorbridge_gs --prefix "XB s" \
      --timeout 320 --runs 4 --minfields 6
