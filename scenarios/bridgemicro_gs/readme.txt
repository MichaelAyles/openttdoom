bridgemicro_gs : isolating the exact recipe to build a rail bridge over a perpendicular lane
=============================================================================================

PURPOSE
-------
A throwaway probe that builds a length-3 N-S rail bridge in four configurations and reports,
per variant, whether the bridge built (GSBridge.IsBridgeTile) and the BuildBridge return. It
exists to find the EXACT preconditions, because the first bridgeprobe attempt silently failed
to build (built4 brfalse) and the GS-API docs do not spell out the ramp-tile requirements.

VARIANTS (each at its own column; bridge spans (x,y0)->(x,y0+2) over middle tile (x,y0+1))
  V1: head/tail ramp tiles EMPTY, under-tile has E-W rail.
  V2: head/tail ramp tiles have N-S rail pre-laid, under-tile has E-W rail.
  V3: head/tail EMPTY, under-tile EMPTY.
  V4: same as V1 at a different row.

RESULT (one fresh run)
  "BM 1ok1n4|0ok0n4|1ok1n4|1ok1n4"   (format per variant: <IsBridgeTile>ok<BuildBridge>n<#types>)
  V1 = 1ok1  built
  V2 = 0ok0  FAILED  <-- the bug: pre-laying N-S rail on the ramp tiles blocks BuildBridge
  V3 = 1ok1  built
  V4 = 1ok1  built

THE RECIPE (used by bridgeprobe_gs and xorbridge_gs)
  - GSBridge.BuildBridge builds the ramps ITSELF; the head/tail tiles must be EMPTY of rail.
  - lay the vertical spur only on rows ABOVE the head and BELOW the tail; the bridge spans the
    gap of three tiles (head, under, tail).
  - the under-tile carries the crossed lane's perpendicular (E-W) rail (build it first; a bridge
    over a plain or perpendicular-rail tile is fine).
  - bridge type: GSBridgeList_Length(DistanceManhattan(head,tail)+1).Begin() (n=4 types here).

HOW TO RUN
  python tools/run_fixed.py --gsname bridgemicro --gsdir bridgemicro_gs --prefix "BM 0" \
      --timeout 120 --runs 1 --minfields 1
(note the latched prefix "BM 0" only matches if variant 1 fails; in practice read the printed
per-name lines "BM v1 ...".)
