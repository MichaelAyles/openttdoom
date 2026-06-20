norchain_gs: a TWO-GATE CHAIN computing OR(a,b) in OpenTTD 15.3
==============================================================

This composes the VERIFIED single computing gate (scenarios/norgate_gs) into a
two-gate chain, the key de-risk between "one gate works" and "a machine works".
It computes OR(a,b) = NOT(NOR(a,b)) entirely out of OpenTTD track, block signals
and parked trains, and proves GATE COMPOSITION: gate 1's output physically drives
gate 2's input.

What it builds
--------------
Each gate is the proven norgate primitive: a bit is train presence on a block, a
normal block signal is red iff its protected (through) block is occupied, and a
reader train run west->east passes the signal iff the block is empty. The reader's
final x is the output (past the signal = 1, held at it = 0).

Two parallel eastbound lanes per chain, joined by a perpendicular coupling spur:

  Gate 1 (lane row gy1): a 2-input NOR of primary inputs a,b. Reader signal SIG1X
  =36 protects the input block (taps a@37, b@38), terminated by SIG1TX=40. The
  reader is ordered to a far east depot; the MOMENT its x reaches the coupling tile
  CPLX=42 it is FROZEN there (StartStopVehicle). So a reader that PASSES SIG1X (both
  inputs absent) parks on CPLX; a reader HELD at SIG1X (an input present) never
  reaches CPLX. (This park behaviour was isolated and validated by main_diag3.nut:
  inputs absent -> rest x = 42 = CPLX; input a present -> rest x = 35, held.)

  Coupling: a vertical spur with NO signal joins CPLX(gy1) to gate 2's input block
  on lane gy2 = gy1+3, so the two are ONE signal block. A gate-1 reader parked on
  CPLX therefore occupies gate 2's input block.

  Gate 2 (lane row gy2): a NOT (one-input NOR). Reader signal SIG2X=40 protects the
  input block (41,42,43) terminated by SIG2TX=44; CPLX=42 lies inside it. The gate-2
  reader passes iff its input block is empty iff gate 1 did NOT pass. So
  gate2 = NOT(gate1) = NOT(NOR(a,b)) = OR(a,b).

Expected composed truth table, OR:  00->0, 01->1, 10->1, 11->1.

Four independent copies, no teardown
------------------------------------
Between cases, tearing down trains on the coupled junction proved fragile (a reader
restarted at the spur junction could loop and never reach a depot, hanging the
script). So instead each of the four cases (a,b) is built as a SEPARATE copy of the
chain at its own band of rows (BASE + case*BAND). Inputs are pre-parked, both
readers are run, and their final x recorded. Nothing is sold; the cases are
physically disjoint and cannot pollute each other.

Readout (relay-independent)
---------------------------
GSLog does not relay to the admin console here, and long company names silently
fail to set (a length limit), so the result is encoded SHORT into the COMPANY NAME,
read with "rcon companies", and updated live (per-case "cXX g1x/g2x" then the final
line). The final name is:

  OR s<SIG2X> <f00> <f01> <f10> <f11>

where f is gate 2's reader final x for that case. External judge: gate2 x > SIG2X
(=40) means the gate-2 reader passed its signal, i.e. OR output = 1; x <= SIG2X
means OR output = 0.

How to run it (headless, on the bundled binary)
-----------------------------------------------
1. Copy this folder to the OpenTTD game dir:
     ~/OneDrive/Documents/OpenTTD/game/norchain_gs/
2. In openttd.cfg [game_scripts] set the first entry to the GS GetName with NO
   spaces:  norchain =
3. Start a dedicated server from the binary dir:
     ./openttd.exe -D -d script=1
4. Found a company for the deity GS to build as, then poll the company name:
     python tools/ottd_admin.py rcon "start_ai"
     python tools/ottd_admin.py rcon "companies"     # repeat until "OR s..." appears
   The build (four chain copies) plus the four case runs take a few minutes of
   in-game time, then the encoded result latches into the company name.

Files
-----
  info.nut         GS metadata (GetName "norchain", no spaces).
  main.nut         the chain: BuildCopy x4, RunCase x4, encode the OR readout.
  main_diag3.nut   the isolation diagnostic that validated the gate-1 park at CPLX.
  main_diag1/2.nut earlier diagnostics (kept for the record; diag1 found the
                   dead-end hold signal does NOT cleanly park the reader, diag2
                   found a premature held-detection misfires; diag3 is the fix).

Honest scope
------------
See ../../STATUS.md and ../../STUCK.md for the run result, the verbatim company-name
readout, and the truth table derived from the raw reader positions. The clock train
(sampling both readers on a shared periodic edge) is the secondary goal; its status
is reported honestly there.
