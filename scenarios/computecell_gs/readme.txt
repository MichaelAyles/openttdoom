computecell_gs: a NOR cell STAMPED FROM A NETLIST that COMPUTES in OpenTTD 15.3
===============================================================================

This is the FUSION milestone. Before this, the toolchain (synth -> place -> route ->
emit) placed and routed a netlist but the GameScript stamped only PLACEHOLDER track,
and SEPARATELY a hand-built GameScript (scenarios/norgate_gs) proved a single NOR
computes. computecell_gs fuses the two: it reads the EMITTED PLACEMENT
(scenario_data.nut, GetScenarioData()) and stamps the verified computing-NOR geometry
at the placed cell position, then proves it computes by reading raw reader positions.

Nothing is hand-coded to fixed map coordinates. The cell origin (cell.x, cell.y) and
the input/output pin tiles all come from place_and_route. Geom()/GeomAt() derive every
gate tile as cell.x/cell.y plus a fixed footprint offset, so moving the cell in the
placement moves the whole gate. The output bits are read from raw GSMap.GetTileX reader
positions, never computed in Squirrel from the inputs.

The footprint is frozen into place_and_route/place.py (CELL_W=14, CELL_H=3, the pin
offsets), which the module header always said was "all that is needed" to swap in the
real stamp. The single-cell SC1 design routes 3/3 with the real footprint; the existing
multi-cell adder place-and-route tests still pass.


STAGE 1 (SC1): a single NOR2 cell. CLOSED, 5/5.
-----------------------------------------------
The toolchain emits a one-cell NOR2 placement (primary inputs a,b, primary output y).
The GS stamps the cell from the placement and sweeps the four input combos (00,01,10,11),
running a fresh reader each combo and reading its raw final x. The reader passes its
signal (x > SIGX) iff its input block is empty iff no input train is present = NOR.

Run:  python tools/run_sc1.py
Readout (company name):  SC1 s<SIGX> <x00> <x01> <x10> <x11>
Verified, 5 back-to-back fresh dedicated-server runs, ALL identical:
    SC1 s19 24 18 12 12
SIGX = 19 (= cell.x + 7, from the placement at origin (12,2)). Judge x > SIGX:
    00 -> 24 > 19  = 1
    01 -> 18 <= 19 = 0
    10 -> 12 <= 19 = 0
    11 -> 12 <= 19 = 0
= 1,0,0,0 = NOR(a,b). Exactly as expected, judged from the RAW reader positions.


STAGE 2 (OR = NOT(NOR(a,b))): a 2-cell chain. CLOSED via fix path (A).
---------------------------------------------------------------------
A 2-cell netlist (gate1 NOR2(a,b) -> net w, gate2 NOT(w) -> y) places and routes 4/4,
and the GS stamps BOTH gates from the placement. gate1's NOR computes correctly INSIDE
the chain (its reader parks at its output tile grest = sig2x+2 = 25 when it passes and is
held at x=18 when an input is present), and now gate2 = NOT(gate1) follows the inter-cell
bit, so the whole chain computes OR. Readout:  OR s24 23 29 29 29.  Judge g2x > 24:
    00 -> 23 <= 24 = 0     (gate1 passed, occupied gate2's input, gate2 held)
    01 -> 29 >  24 = 1     (gate1 held, gate2 input empty, gate2 passed)
    10 -> 29 >  24 = 1
    11 -> 29 >  24 = 1
= 0,1,1,1 = OR(a,b), exactly, judged from the RAW gate2 reader x.

THE FIX (path A, placement-constrained chain layout). The earlier failure was the
inter-cell coupling: the toolchain places gate2 ~17 tiles east of gate1, so the bit had
to cross a long horizontal gap, and a hand-laid L-coupling over that gap does NOT merge
the two signal blocks in OpenTTD 15.3 (block/reservation behaviour). norchain only worked
because gate2's input block OVERLAPPED gate1's frozen rest tile via a SHORT PURE-VERTICAL
signal-free spur (3 tiles, no horizontal run). So RunCopyOR now applies that as a CHAIN
PLACEMENT CONSTRAINT derived from the placement: gate1 is stamped at its placed origin,
and gate2 (the consumer) is CO-LOCATED three rows below it with its input TAP column set to
exactly gate1's frozen rest column grest (g2bx = grest-7, so the Geom tap = g2bx+1+6 lands
on grest). The coupling is then the proven norchain spur: a 3-row pure-vertical no-signal
track at x=grest joining gate1's output block to gate2's input block as ONE block. Every
coordinate is derived from the PLACED gate1 origin (g0cell.x/.y), so moving gate1 in the
placement moves the whole chain; the link is verified to be the EMITTED routed net w
(g0cell.output.net == g1cell.inputs[0].net), not an assumption. The bit transfers
PHYSICALLY: gate1's passing reader, frozen on grest, occupies gate2's input block over the
spur; gate2's reader is then held. No OR is computed in Squirrel.

Two facts were load-bearing (both empirical):
  - gate1's east depot must be FAR past grest (grest+5), like norchain's depot at CPLX+4.
    With a near depot the passing reader rolls INTO the depot (removed from the block)
    before the freeze catches it, so the merge reads empty and gate2 wrongly passes
    (observed once as OR s24 29 29 29 29 before the depot was moved out).
  - reader launches occasionally flake on a fresh server (a transient invalid BuildVehicle
    handle, seen as g1x=-1 or a reader stalled at a low x like 17). BuildAndLaunch retries
    the build until the handle is valid and dispatches it out of the depot, which removes
    the flake.

To reproduce Stage 2:  python tools/run_or.py
Readout:  OR s<g2sigx> <g2x00> <g2x01> <g2x10> <g2x11>  (g2x > g2sigx => OR 1, expect 0,1,1,1)
Per-case live name "OR cXX g1x/g2x" shows both gates: g1x=25 (pass) for 00 / 18 (held) for
01,10,11 (gate1 NOR computes from the placed gate), and g2x following as NOT(gate1).


Files
-----
  info.nut    GS metadata (GetName "computecell", no spaces).
  main.nut    Geom/GeomAt (placement-derived geometry), StampGeom (the parameterised stamp),
              the SC1 sweep (Start), and the Stage 2 OR chain (StartOR/RunCopyOR).
  ../../tools/run_sc1.py   emit the 1-cell placement + run + read the SC1 company name.
  ../../tools/run_or.py    emit the 2-cell placement + run + read the OR company name.
  ../../place_and_route/place.py   the real CELL_W/CELL_H footprint + pin offsets.
