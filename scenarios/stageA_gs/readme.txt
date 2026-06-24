stageA: a FIXED THREE-GATE CHAIN, deeper than norchain's two, proving the fixed signal-free
coupling composes PAST two gates. This is the architecture proof that breaks the composition
wall the selffib adder hit (its 0.7^18 reused-lane choreography collapse, STUCK.md #9).

NETWORK (each gate its OWN lane, wired by FIXED pure-vertical signal-free coupling spurs, built
ONCE per input combo, NO per-gate train re-parked or disposed between reads):
    g0 = NOR(a, b)   -> n0
    g1 = NOR(n0, a)  -> n1     (reads coupling n0 from g0 AND a fresh primary a tap)
    g2 = NOR(n1)     -> y      (a NOT; the output)
Expected y over (a,b) = 00,01,10,11: 1,0,1,1, judged from RAW g2 reader x (x > SIG2X == 1).

MECHANISM (reused verbatim from norchain): a bit is train-presence on a protected through-block;
a reader passes a normal block signal iff its input block is empty (== NOR of the present
inputs). A PASSING driver reader is FROZEN the instant it clears its terminating signal, on its
coupling tile CPL; a SHORT PURE-VERTICAL signal-free spur joins CPL into the consumer's input
block (3 rows below, straddling CPL), merging the two signal blocks, so "driver output 1" ==
a train parked in the consumer's input block. Each stage marches +3 in x and +3 in y.

Two crux fixes over a naive stacking of norchain (both found by running, not guessed):
  - a DRIVER gate (one that feeds a downstream gate) needs a FAR east depot (CPL+6) so its
    passing reader rests on open track to be frozen, not rolled into a near depot. With g1's
    east depot only +2 past its CPL the passing reader never occupied g2's input (g2 always
    read empty, the chain computed one inversion short).
  - the freeze must be caught EARLY and tightly: CPL is the FIRST tile past the terminating
    signal, the poll is Sleep(3), and the reader is frozen on x >= CPL OR the moment it passes
    the reader signal and leaves its row (started down the spur). A slow poll let the passing
    reader roll to the far depot before it was frozen, again leaving the consumer empty.

RUN:  python tools/run_fixed.py --gsname stageA --gsdir stageA_gs --prefix "STGA s" \
          --minfields 6 --timeout 300 --runs 4
Readout via the company name (rcon companies): "STGA s44 <g2x00> <g2x01> <g2x10> <g2x11>", plus
live per-combo intermediates "a<ab> <g0x>/<g1x>/<g2x>" showing every gate's raw reader x.

VERIFIED: "STGA s42 43 41 43 43" = 1,0,1,1 (g2 x>42 == 1), reproduced across fresh
dedicated-server runs. Per-combo intermediates confirm the chain internally, e.g. a00 41/38/43
(g0 frozen at CPL0=41, g0 passed n0=1; g1 held at 38, n1=0; g2 passed 43, y=1) and a01 35/44/41
(g0 held, n0=0; g1 frozen at CPL1=44, n1=1; g2 held 41, y=0). All judged from RAW positions, no
logic computed in Squirrel.
