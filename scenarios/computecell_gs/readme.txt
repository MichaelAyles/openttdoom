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


STAGE 2 (OR = NOT(NOR(a,b))): a 2-cell chain. PARTIAL, blocker documented.
--------------------------------------------------------------------------
A 2-cell netlist (gate1 NOR2(a,b) -> net w, gate2 NOT(w) -> y) places and routes 4/4,
and the GS stamps BOTH gates from their placed origins. gate1's NOR computes correctly
INSIDE the chain: its reader parks at its output tile grest = sig2x+2 = 25 when it passes
(inputs absent) and is held at x=18 when an input is present, i.e. 1,0,0 for combos
00,01,10, read raw. This reproduces the norchain gate-1 behaviour from the PLACED gate.

What does NOT close is the inter-cell COUPLING. The placement separates gate1 and gate2
by the routing channel (gate1 output rests at x=25, gate2 input block is at x=42..43), so
the bit must cross a ~17-tile horizontal gap to enter gate2's input block. The GS lays an
L-shaped no-signal coupling (branch down off gate1's output block, an intermediate row east,
then down into gate2's input block) intended to make gate1's output block and gate2's input
block ONE signal block. In game, that long hand-laid L-coupling does NOT reliably merge the
two blocks: with gate1 parked on its output tile, gate2's reader still passes (its input
block reads empty), so the coupling occupancy is not propagating across the gap. Removing
gate1's east depot to force the reader down the coupling instead triggers the norchain
"reader held a tile early" misfire (the reader stops at a tap, x=20, never reaching the
coupling), because the coupling does not present a clean through block.

This is the same class of obstacle STUCK.md isolated: multi-tile coupling track in OpenTTD
15.3 has block/reservation behaviour that a hand-laid L over a placement-sized gap does not
satisfy. norchain made composition work only because it HAND-PLACED gate2's input block to
overlap gate1's natural rest tile (a 3-tile pure-vertical spur, no horizontal run). With the
cells at toolchain-placed positions the spur becomes a long L and the merge fails.

Honest precise blocker for the human: the coupling must reproduce the channel router's actual
routed path for net w (which crosses the gap as a real connected track, with bridges at
perpendicular crossings), OR the placer must co-locate a driver's output rest tile with its
consumer's input block (a placement constraint), OR the inter-cell bit must be carried by a
moving train clocked across the gap rather than a static block-merge. The L-merge is not it.

To reproduce Stage 2:  python tools/run_or.py
Readout:  OR s<SIG2X> <g2x00> <g2x01> <g2x10> <g2x11>   (g2x > SIG2X => OR 1, expected 0,1,1,1)
Observed gate1 in-chain (per-case company name "OR cXX g1x/g2x"): g1x = 25 (pass) for 00,
18 (held) for 01/10, confirming the PLACED gate1 NOR computes; the gate2 column does not yet
follow because the coupling does not merge.


Files
-----
  info.nut    GS metadata (GetName "computecell", no spaces).
  main.nut    Geom/GeomAt (placement-derived geometry), StampGeom (the parameterised stamp),
              the SC1 sweep (Start), and the Stage 2 OR chain (StartOR/RunCopyOR).
  ../../tools/run_sc1.py   emit the 1-cell placement + run + read the SC1 company name.
  ../../tools/run_or.py    emit the 2-cell placement + run + read the OR company name.
  ../../place_and_route/place.py   the real CELL_W/CELL_H footprint + pin offsets.
