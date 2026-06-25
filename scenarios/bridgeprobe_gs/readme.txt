bridgeprobe_gs : the BRIDGE CROSSING primitive, proven in isolation (STUCK.md #9 fix)
========================================================================================

WHAT IT PROVES
--------------
A signal-free COUPLING SPUR (a vertical track that carries a driver gate's bit into a
consumer gate's input block) must sometimes CROSS a perpendicular reader LANE of a
second, independent gate. At a LEVEL crossing the junction merges the two tracks into
ONE signal block, SHORTING the spur into the lane (the wall that caps flat networks at
depth-1 reconvergence, STUCK.md #9). The FIX is a BRIDGE: in OpenTTD 15.3 a bridge tile
and the tile UNDER it are SEPARATE map tiles in SEPARATE blocks, so the spur goes OVER
the lane, staying coupled to the consumer while leaving the crossed lane isolated.

This probe builds two INDEPENDENT nets that cross, once with a BRIDGE and once at LEVEL
(the control), and reads BOTH nets from RAW reader positions (GSMap.GetTileX), encoded
into the company name. No Squirrel logic decides any bit.

  NET A (the coupling): a DRIVER train parked on the spur top, joined by the spur down to
    a CONSUMER NOT gate. consumer = NOT(driver bit).
  NET B (the crossed lane): an independent NOT gate whose horizontal reader lane the spur
    crosses. crossed = NOT(its own input).

THE EMPIRICAL BRIDGE RECIPE (found by scenarios/bridgemicro_gs)
--------------------------------------------------------------
GSBridge.BuildBridge(GSVehicle.VT_RAIL, type, head, tail) builds the ramps ITSELF, so:
  - DO NOT lay rail on the head/tail ramp tiles (laying N-S rail on a ramp makes the build
    FAIL: bridgemicro variant v2 = 0ok0, vs v1/v3/v4 = 1ok1 with empty ramps).
  - the under-tile carries the crossed lane's perpendicular (E-W) rail; build it FIRST.
  - a length-3 N-S bridge spans (x, LY-1) -> (x, LY+1) over the lane tile (x, LY).
  - verify-and-retry the build (busy command queue) and verify the under-tile rail first.

RESULT (4 fresh dedicated servers, all identical, judged from RAW x)
--------------------------------------------------------------------
Readout: "BP cs36 ls36 br 35 44 44 35"  (C_SIG=36, L_SIG=36; br <Aconsumer> <Acrossed>
<Bconsumer> <Bcrossed>). Judge: consumer x>36 => 1, crossed x>36 => 1.

  BRIDGE copy A (driver=1, crossed input=0):
    consumer x=35 (<=36) HELD  -> 0 = NOT(driver 1)   coupling transferred through the bridge
    crossed  x=44 (>36)  PASS  -> 1 = NOT(input 0)    crossed lane computed correctly, NOT shorted
  BRIDGE copy B (driver=0, crossed input=1):
    consumer x=44 (>36)  PASS  -> 1 = NOT(driver 0)   correct
    crossed  x=35 (<=36) HELD  -> 0 = NOT(input 1)    correct

BOTH nets compute their TRUE values with the bridge. ISOLATION PROVEN.

CONTROL (level crossing, the failure the bridge fixes): "BP lv 35 35 35 35"
    every reader HELD at x=35 regardless of input: the level junction merged the spur and
    lane into ONE block, so the parked driver / crossed reader short each other. Both nets
    read 0 always (wrong). This is exactly the short the bridge removes.

RELIABILITY: after the under-tile-verify + bridge-retry hardening, 4/4 fresh runs are
clean and identical (built4 brtrue). Before the fix, the first copy occasionally failed to
bridge (built4 brfalse); the fix is to confirm the perpendicular under-rail exists before
calling BuildBridge and to retry the bridge build.

HOW TO RUN
----------
  python tools/run_fixed.py --gsname bridgeprobe --gsdir bridgeprobe_gs --prefix "BP cs" \
      --timeout 300 --runs 4 --minfields 8
(latch the level-control line instead with --prefix "BP lv" --minfields 7.)
