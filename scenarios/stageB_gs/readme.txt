stageB: a FIXED HALF-ADDER SUM bit (a XOR b) as a 6-gate NOR network on trains. The real
target: it proves the fixed signal-free coupling composes through FAN-OUT and RECONVERGENT
FAN-IN, past the 2-gate norchain and the 3-gate stageA chain. Companion: stageBcarry_gs (the
carry = a AND b).

NETWORK (merge-free; the fan-out driver NOR(a,b) is DUPLICATED as g0a, g0b so every gate drives
exactly ONE consumer block, the proven norchain coupling, never a block-merge fan-out which
would corrupt the two distinct consumer input blocks):
    g0a = NOR(a, b)  -> n1a      g0b = NOR(a, b)  -> n1b
    g1  = NOR(a,n1a) -> n2       g2  = NOR(b,n1b) -> n3
    g3  = NOR(n2,n3) -> n4       g4  = NOR(n4)    -> y
Expected y over (a,b) = 00,01,10,11: 0,1,1,0 = XOR, judged from RAW g4 reader x (x > F_SIG == 1).

KEY GEOMETRY IDEA for the reconvergence (g3 = NOR(n2,n3), two drivers into one block): place g3
BETWEEN its drivers, g1 directly ABOVE (coupling spur DOWN) and g2 directly BELOW (coupling spur
UP), so both couplings are short and adjacent. A spur merges the block regardless of direction,
so an UP spur works exactly like a DOWN spur. The single non-adjacent edge (g3 -> g4) is routed
at a far-east column (g3's CPL pushed to x=50 with filler track) kept clear of the intervening
lanes (g2, g0b end west of column 50). All gate lanes and spurs are collision-checked.

Every gate has its OWN lane; gates wired by FIXED pure-vertical signal-free coupling spurs;
built ONCE per input combo (four SEPARATE physical copies at their own row bands, since teardown
on a coupled junction hangs the script, per norchain); the six readers run in topological order
(g0a, g0b, g1, g2, g3, g4), each FROZEN on its CPL if it passes. NO per-gate train is re-parked
or disposed between reads. Same freeze mechanism as stageA (far driver depots, tight early
freeze on the first tile past the terminating signal).

RUN:  python tools/run_fixed.py --gsname stageB --gsdir stageB_gs --prefix "STGB s" \
          --minfields 6 --timeout 420 --runs 4
Readout via the company name: "STGB s49 <g4x00> <g4x01> <g4x10> <g4x11>", plus live per-combo
intermediates "b<ab> <g3x>/<g4x>".

VERIFIED: "STGB s49 48 54 54 48" = 0,1,1,0 = XOR (g4 x>49 == 1), judged from RAW positions, no
XOR computed in Squirrel. Per-combo intermediates confirm the reconvergence, e.g. b00 50/48
(g3 frozen at C_CPL=50, g3 passed n4=1; g4 held 48, y=0) and b01 40/54 (g3 held, n4=0; g4 passed
54, y=1). The MECHANISM is proven: every CLEAN run reads exactly 0,1,1,0.

RELIABILITY (honest): the first batch (5 fresh runs incl. the initial one) gave a clean
"STGB s49 48 54 54 48" = 0,1,1,0 in 3 of 5, and a whole-run failure "STGB s49 54 54 54 54" =
1,1,1,1 in 2 of 5. The failure is SYSTEMATIC-per-run at the reconvergence: when g3 fails to
freeze on its far CPL=50 it stops short (x 40-42, before its terminating signal), so the g3->g4
coupling never delivers and ALL combos read y=1. Root cause: g3's CPL is pushed 6 tiles east of
its terminating signal (filler track) to clear the g3->g4 output spur over the intervening
lanes, and that long post-terminating run was a DEAD-END block, so g3's terminating signal could
sit red (a normal signal in front of a dead-end block stays red) and hold g3's reader before it
reached CPL. FIX (BuildLane term2x): a THIRD terminating signal east of CPL makes g3's freeze
block a proper THROUGH block, so g3 reliably passes its terminating signal and rests on CPL=50.
This is the same dead-end-block gotcha that the single-gate work documented, here applied to the
freeze block of a gate with a far-pushed coupling.
