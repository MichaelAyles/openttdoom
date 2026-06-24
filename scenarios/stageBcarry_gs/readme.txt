stageBcarry: the half-adder CARRY bit (a AND b) as a FIXED 3-gate NOR network on trains, the
companion to stageB (the SUM = XOR). Carry = AND(a,b) = NOR(NOT a, NOT b):
    g0 = NOR(a)     -> na      (NOT a; root, primary input a)
    g1 = NOR(b)     -> nb      (NOT b; root, primary input b)
    g2 = NOR(na,nb) -> c       (reconvergent fan-in; the output)
Expected c over (a,b) = 00,01,10,11: 0,0,0,1 = AND, judged from RAW g2 reader x (x > C_SIG == 1).

GEOMETRY: the reconvergence g2 = NOR(na, nb) sits BETWEEN its two drivers, g0 directly ABOVE
(coupling spur DOWN) and g1 directly BELOW (coupling spur UP), so both fixed signal-free spurs
are short and adjacent and there is NO skip across a foreign lane. Same proven mechanism as
norchain / stageA / stageB: a bit is train-presence on a protected block; a passing driver
reader is frozen on its coupling tile; a short pure-vertical signal-free spur merges it into the
consumer's input block. Built ONCE per combo, four SEPARATE copies, no per-gate train re-parked.

RUN:  python tools/run_fixed.py --gsname stageBcarry --gsdir stageBcarry_gs --prefix "STBC s" \
          --minfields 6 --timeout 300 --runs 4
Readout: "STBC s38 <g2x00> <g2x01> <g2x10> <g2x11>". Judge: x > 38 == carry 1, so a correct
AND reads 0,0,0,1 (only the 11 combo above the signal).

VERIFIED: "STBC s38 37 37 37 43" = 0,0,0,1 = AND, judged from RAW positions. Reproduced in 3 of
4 fresh dedicated-server runs FULLY clean, the 4th "STBC s38 37 37 -1 43" = 0,0,(miss),1 with a
single dispatch flake on combo 10 (the reader not caught, a combo whose carry is 0 anyway) and
the only carry-1 case (11 -> 43) correct. Per-combo intermediates confirm the network, e.g.
c00 39/38/37 (g0 NOT a frozen at 39 passed na=1, g1 NOT b at 38 passed nb=1, g2 held 37,
carry=0). RELIABLE like stageA: a simple fan-in with adjacent up/down couplings and no far-pushed
CPL, so it does not hit the reconvergent-gate freeze flake that bounds stageB's XOR.
