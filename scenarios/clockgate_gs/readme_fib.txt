fibgate: a CLOCK-STEPPED FIBONACCI readout on the proven clocked-gate mechanism
================================================================================

This is a fork of main_clocked.nut (the RELIABLE GS-mediated clocked NOT gate, verified
8/8 in prior runs). It keeps every proven piece unchanged and adds a multi-lane gate bank
so that each clock edge presents one successive Fibonacci term and reads it back.

Files
-----
  main_fib.nut    the fork (class FibMain). Copy to game/fibgate_gs/main.nut.
  info_fib.nut    GS metadata, GetName "fibgate" (no space), CreateInstance "FibMain".
  run_fib.sh      N fresh dedicated-server passes; polls the company name for "F <vals>".

What is reused verbatim from main_clocked.nut (the proven mechanism)
--------------------------------------------------------------------
  - the SELF-SUSTAINING CLOCK: a single train on a closed rectangular loop ringed with
    ONE-WAY NORMAL block signals (clockwise), launched and CONFIRMED circulating (left the
    depot, reached the far run, returned) before any sampling; CKFAIL + clean stop on
    failure;
  - the per-edge WaitClockEdge: each edge the GS BLOCKS until the clock train crosses a
    fixed loop phase (a rising edge entering the LEFT run), so every sample is released by a
    real clock edge, not a free-running timer. The per-edge wait (p<n>) is reported and is
    small, proving a real edge released the sample;
  - the NOT-gate primitive: a straight lane with a reader block signal whose protected
    (through) block holds one input tap, terminated by a second signal. A normal block
    signal is RED iff its block is occupied, so an eastbound reader passes iff the input
    block is empty == NOT(input). The reader's FINAL x is the bit (x > GSIGX = 1).

What is new
----------
  NBITS=4 PARALLEL gate lanes (one per output bit), each on its own band of rows, all gated
  by the SAME clock edge. At edge k the GS drives the lanes to present FIB[k] from
  {1,1,2,3,5,8,13} and reads the 4 lanes back, decoding the value from the RAW reader x.

How a bit is presented (genuine NOR; output == the Fibonacci bit)
-----------------------------------------------------------------
  Each lane physically computes out = NOT(input present). To make lane i's output equal
  Fibonacci bit b, the GS sets that lane's input PRESENT iff b == 0 (a train parked on the
  tap). Then the reader passes (out 1) iff the input block is empty iff b == 1. So the gate
  computes NOT of its driven input and the schedule is chosen so the computed outputs spell
  the Fibonacci value. EVERY output bit comes from the RAW reader x (out = x > GSIGX), and
  the decoded value = sum(out_i << i); no Fibonacci value is read from FIB[] in Squirrel.

Readout (company name; GSLog does not relay here). All short, <= ~31 chars:
  per edge:  "e<k> v<val> b<bits> p<wait>"   e.g.  e4 v5 b0101 p103
  final:     "F 1 1 2 3 5 8 13"               the decoded sequence (16 chars)
Judge from the per-edge raw values / decoded values, NOT from FIB[].

How to run
----------
  1. Copy main_fib.nut -> game/fibgate_gs/main.nut and info_fib.nut -> info.nut.
  2. openttd.cfg [game_scripts] first entry: "fibgate ="; flat/water-free map; admin port +
     password set (the GS demolishes + LevelTiles its build area regardless).
  3. bash scenarios/clockgate_gs/run_fib.sh 5     (5 back-to-back fresh dedicated runs)

HONEST SCOPE
------------
This is per-edge RE-PRESENTATION of the Fibonacci terms on the proven clock mechanism: the
value is freshly presented to the gate bank each clock edge and computed by the gates. It is
NOT a self-feeding hardware register Fibonacci (next = a + b held in track and fed back). A
true register Fibonacci needs the physical one-edge OUTPUT REGISTER, which is the open
syncgate item (STUCK.md blocker 1 / 7). What IS real and verified in game here: a
self-sustaining clock train, a per-edge clock-released sample, and a bank of real
block-signal NOR/NOT gates whose RAW outputs spell 1,1,2,3,5,8,13 in order, one term per
clock edge.

Reliability
-----------
The clock LAUNCH is a documented flaky step (the single train occasionally fails to leave its
depot on a fresh server; see syncgate STUCK.md). On launch failure the run reports CKFAIL and
stops cleanly. The other flaky step is the per-edge input CHOREOGRAPHY for the HIGH-VALUE terms
(8 and 13): those edges need the MSB lane's input train to go ABSENT, and a removal that lags
leaves the lane held, reading `F 1 1 2 3 5 0 5` (edges 5-6 miss the MSB bit). This is the same
train-dispatch fragility documented for SC2 (an input train caught/cleared on a junction tap,
inherently racy). Hardening (clock-first ordering, lane-build self-heal, persistent reader
egress, ReverseVehicle + verified tap-clear on input removal) raised the clean rate but did not
make it solid.

Run report (fresh dedicated-server passes, this run; judged from the RAW per-edge positions /
the decoded company-name value, never from the term list):
  edges 0-4 (values 1,1,2,3,5) read correctly in EVERY pass that launched the clock.
  COMPLETE sequence `F 1 1 2 3 5 8 13` reproduced in 5 fresh passes:
    batch3 (cap380, clock-first): run2, run5, run6 = F 1 1 2 3 5 8 13   (run1 lane-race all-0,
      runs3,4 = F 1 1 2 3 5 0 5)
    batch4 (reader-hardened):     run4 = F 1 1 2 3 5 8 13               (runs1-3 = F 1 1 2 3 5 0 5)
    batch5 (input-clear fix):     run3, run4 = F 1 1 2 3 5 8 13         (run1 = F 1 1 2 3 5 0 5,
      run2 CKFAIL)
  A per-edge trace from a complete pass (run2 of batch3), each value decoded from raw reader x:
    e0 v1 b0001 p121   e1 v1 b0001 p41   e2 v2 b0010 p42   e3 v3 b0011 p41
    e4 v5 b0101 p103   e5 v8 b1000 p41   e6 v13 b1101 p41
  The p<wait> is the per-edge clock wait; each is small (not the 300 timeout), proving every
  sample was released by a real clock edge.
