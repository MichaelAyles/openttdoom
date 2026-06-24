selffib_gs: a SELF-FEEDING FIBONACCI on OpenTTD trains
======================================================

1,1,2,3,... computed from the machine's OWN held register state, on the hardened
clock launch. No Fibonacci/sequence array exists anywhere in the GameScript: each
output term is next = a + b, where a and b are read out of HELD registers (parked
trains) at RAW reader positions, the addition is done by a REAL block-signal NOR
full adder whose sum bits are read at RAW reader positions, and the window is then
shifted (a <- b, b <- next) back into the held registers. The output sequence is
produced purely by the machine feeding its own held state back through the gates.

This is the toggle (scenarios/toggle_gs, next = NOT(held Q) from one real gate)
scaled up: two multi-bit registers and a multi-bit adder instead of one bit and one
NOT, with the same honest boundary (the write-BACK is GS-mediated, because pure
track feedback hits the OpenTTD reservation-coupling blocker documented in
scenarios/syncgate_gs).

How it works
------------
HELD BIT (register_gs cell, one per register bit). Q = the PRESENCE of a parked
train on a HOLD tile inside a protected (through) block. A normal block signal is
RED iff its block is occupied, so a fresh eastbound reader from the west depot is
HELD (raw x <= RSIGX) iff the HOLD train is present (bit 1) and PASSES east
(x > RSIGX) iff HOLD is empty (bit 0). A parked train persists forever: that is the
memory. Register a is NBITS cells on rows AY0.., register b on rows BY0...

NOR FULL ADDER (norgate_gs primitive, every output a raw read). The only buildable
gate is the block-signal NOR: a reader passes a signal iff every input tap in the
protected block is empty. NOR is universal, so a full adder is nine NOR gates:
    n1 = NOR(a,b)
    n2 = NOR(a,n1);  n3 = NOR(b,n1);  n4 = NOR(n2,n3)        = a XOR b
    n5 = NOR(n4,c);  n6 = NOR(n4,n5); n7 = NOR(c,n5)
    sum  = NOR(n6,n7)                                          = a XOR b XOR c
    cout = NOR(n5,n1)                                          = majority(a,b,c)
(this netlist is checked exhaustively in Python, all 8 rows match a+b+c.) Each NOR
is ONE physical block-signal read: park the two input bits as trains on the gate
lane's two taps, run a fresh reader, read its raw pass/hold outcome (x > GSIGX => 1).
The output of every gate, INCLUDING sum and cout, is a RAW reader position, never an
arithmetic result computed in Squirrel. The carry ripples bit-to-bit as a real read
fed forward. The only Squirrel role is wiring which raw output feeds which next-gate
tap, exactly the role norchain's coupling spur plays in hardware.

SELF-FEEDING SHIFT. After next = a+b is read bit-by-bit off the gates, the window
shifts: a <- b, b <- next, written back into the held registers (build/park a HOLD
train for a 1 bit, remove it for a 0 bit). The values written are the hardware reads
of the held state, never a stored sequence. So term[k+1] = term[k] + term[k-1] is
the machine feeding its own held state back.

INITIALISATION a=0, b=1, giving 1,1,2,3,...

The clock is the hardened one-way block-signalled loop + per-edge WaitClockEdge,
launched by LaunchClockConfirmed (NudgeEgress one-toggle-per-settle, movement-
verified egress, teardown-and-retry), the same 10/10-clkOK launch as register_gs /
toggle_gs / clockgate main_clocked.

Honest scope and reliability (what is VERIFIED in fresh runs, and where it BREAKS)
---------------------------------------------------------------------------------
VERIFIED in fresh dedicated-server runs (read via the company name, judged from raw
positions, no logic in Squirrel):
  - The HELD REGISTERS self-feed-read correctly: per-edge "e0 rd a0 b1" reproduced the
    held a=0, b=1 from the parked register trains at raw reader positions (the toggle/
    register read primitive, generalised to 2-bit registers).
  - A SINGLE block-signal NOR gate computes correctly (scenarios/selffib_gs/diag.nut,
    the gate-lane isolation harness): NOR(0,0) -> reader passes to x=52 (output 1),
    NOR(0,1) and NOR(1,0) -> reader held at x=45 (output 0). So the adder's gate
    primitive is real and correct on this geometry.
  - The 9-NOR full-adder NETLIST is exhaustively correct (Python: all 8 rows of a+b+c).
  - The hardened clock launch runs (one CKFAIL observed across runs, the documented
    ~1/3 flaky-launch step, retried by LaunchClockConfirmed).

WHERE IT BREAKS (honest, precisely located). Reliability COMPOUNDS: a 2-bit edge does
4 register reads + 2 x 9 = 18 sequential block-signal NOR reads on ONE reused gate lane
+ the shift writes. The wall is REUSING ONE LANE for many sequential gate reads: after a
read, disposing the reader and any tap train and confirming the block is empty for the
NEXT read is the same OpenTTD train-choreography fragility documented in STATUS.md (SC2:
"per-case choreography ~3/5 reliable, 0.7^N collapses; the real fix is deterministic
placement by construction"). Concretely the failures observed and each fix that moved the
wall: (a) a too-short reader SETTLE misread every NOR as held=0 (fixed: Sleep(16)x20 so
the reader has time to travel the lane, verified in diag); (b) a leftover tap/held reader
JAMMED the next NOR's block, read as occupied (fixed: drive disposal trains EAST to the
gate depot, not reverse-to-feeder); (c) the 3rd+ sequential READER then stalls at its
depot exit (egress flakiness), so a full 18-read edge does not reliably complete and the
run reports "FF g" (a gate read failed). So the genuine adder breaks at GATE COMPOSITION
reliability on a reused lane, NOT at the logic (every single gate read that completes is
correct).

The deterministic fix (not built here, the open item): give each of the 9 NOR gates its
OWN lane and couple the held register/carry trains through fixed spurs (the norchain
composition) so NO per-gate train is re-parked or disposed between reads, the way the
toggle read its held bit through ONE fixed NOT gate with no tap-parking and was 8/8. That
removes the per-gate disposal entirely; the reused-lane version here hits the choreography
wall at ~18 reads/edge.

NBITS = 2 (registers hold 0..3) targets the output 1,1,2,3: b reaches 3, and 2+3=5
would overflow a 2-bit b, which is the clean stopping point. NEDGES = 4.

Readout (SHORT, the ~31-char company-name limit)
------------------------------------------------
Per edge: "e<k> a<av> b<bv> s<sum> n<count>"  (held a, held b, computed next read off
the gates, vehicle count). Final: "FF <t0> <t1> ..." the output terms. A failed read
shows "e" (register read) or "g" (gate read) in the term list and stops the run.
Judge from the RAW per-edge reads: each output term is next read off the gates, every
sum bit a raw block-signal NOR pass/hold.

How to run
----------
  bash scenarios/selffib_gs/run_fib.sh [RUNS] [POLLS]
syncs main.nut + info.nut into ~/OneDrive/Documents/OpenTTD/game/selffib_gs/, then
for each run kills openttd, relaunches ./openttd.exe -D -d script=1, start_ai Idle,
and polls the company name until "FF <terms>" / CKFAIL / timeout, printing every
distinct readout. openttd.cfg [game_scripts] first entry = selffib (GetName).
ONE openttd / ONE admin connection at a time.

Files
-----
  main.nut   the GameScript (clock, register cells, NOR gate lane, full adder, the
             self-feeding edge loop).
  info.nut   GS metadata (GetName = selffib, no space).
  run_fib.sh back-to-back fresh-server runner + company-name poller.
