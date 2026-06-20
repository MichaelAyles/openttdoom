"""Scenario emitter for the openttdoom M3 backend: Netlist -> placed, routed Scenario.

This is the top of the place-and-route stack. build_scenario() places cells (place.py),
routes nets (route.py), assigns IO pads for the primary inputs/outputs, and packs the
primary outputs into a small Framebuffer. The result is a Scenario, which scenario.py
serialises to JSON and to the .nut data table the OpenTTD GameScript reads.

IO mapping (per the brief):
  - ports.inputs  -> input pads on the LEFT edge of the map, one row per input.
  - ports.outputs -> output pads plus a 1 x N Framebuffer on the RIGHT edge, so the
    final signal states show up as a row of "pixels" (signals) that the viewer reads.

CLI:
  python -m place_and_route.emit <netlist.json> <out.scenario.json>
writes the Scenario JSON and the sibling .nut (out.scenario.nut).

stdlib only.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

# Allow `python -m place_and_route.emit ...` to run standalone: put this package's own dir
# (place.py / route.py / scenario.py) and the sibling synth/ (netlist.py) on the path. Under
# pytest the repo conftest already does this, so the inserts are harmless no-ops there.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _d in (_HERE, os.path.join(_ROOT, "synth")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from netlist import Netlist
from scenario import Scenario, IOPad, Framebuffer, Clock
from place import place_cells, Placement
from route import route_nets, RouteResult


# Margin of empty tiles kept around the placed logic on the right/bottom for IO + routing.
RIGHT_MARGIN = 6
BOTTOM_MARGIN = 4


def _map_size(placement: Placement) -> tuple:
    """Choose a square-ish map big enough for the logic plus IO margins.

    OpenTTD map dimensions must be powers of two; we round up to the next power of two
    that fits, clamped to a sensible floor so tiny circuits still get a 64x64 map.
    """
    need_w = placement.width_tiles + RIGHT_MARGIN
    need_h = placement.height_tiles + BOTTOM_MARGIN

    def pow2_at_least(n: int, floor: int = 64) -> int:
        v = floor
        while v < n:
            v *= 2
        return v

    return pow2_at_least(need_w), pow2_at_least(need_h)


def build_scenario(netlist: Netlist, name: str | None = None) -> tuple:
    """Place + route `netlist` into a Scenario. Returns (Scenario, RouteResult).

    The RouteResult is returned alongside so callers (tests, CLI) can report routed-net
    coverage and any unrouted nets honestly instead of hiding routing failures.
    """
    netlist.validate()
    placement = place_cells(netlist)
    map_w, map_h = _map_size(placement)

    # Assign IO pad tiles BEFORE routing so the router can run tracks out to them. Input
    # pads sit on the left edge (x = 0), one per row; output pads on the right edge
    # (x = map_w - 1), one per row. Routing then physically connects pad <-> logic, so the
    # reconstruction check can follow the track from the framebuffer back to the gates.
    io: List[IOPad] = []
    input_pads: Dict[str, tuple] = {}
    for i, port in enumerate(netlist.ports.inputs):
        pad_y = min(i, map_h - 1)
        io.append(IOPad(port=port, net=port, x=0, y=pad_y, kind="input"))
        input_pads[port] = (0, pad_y)

    out_x = map_w - 1
    output_pads: Dict[str, tuple] = {}
    fb_pixels: List[str] = []
    for j, port in enumerate(netlist.ports.outputs):
        pad_y = min(j, map_h - 1)
        io.append(IOPad(port=port, net=port, x=out_x, y=pad_y, kind="output"))
        output_pads[port] = (out_x, pad_y)
        fb_pixels.append(port)

    rr: RouteResult = route_nets(netlist, placement, map_w, map_h,
                                 input_pads=input_pads, output_pads=output_pads)

    framebuffer = None
    if fb_pixels:
        framebuffer = Framebuffer(
            origin_x=out_x, origin_y=0, w=1, h=len(fb_pixels),
            pixel_nets=fb_pixels)

    scen = Scenario(
        name=name or netlist.name,
        map_x=map_w, map_y=map_h,
        clock=Clock(period_ticks=8, origin_x=0, origin_y=map_h - 1),
        cells=placement.cells,
        routes=rr.routes,
        io=io,
        framebuffer=framebuffer,
    )
    return scen, rr


def _cli(argv: List[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m place_and_route.emit <netlist.json> <out.scenario.json>",
              file=sys.stderr)
        return 2
    in_path, out_path = argv[1], argv[2]
    netlist = Netlist.load(in_path)

    # Place-and-route operates on the buildable {NOR, CONST0, CONST1} set. If the input
    # netlist still has high-level gates, lower it first so placement only sees buildables.
    if any(c.type not in ("NOR", "CONST0", "CONST1") for c in netlist.cells):
        netlist = netlist.to_nor()

    scen, rr = build_scenario(netlist)
    scen.save(out_path)

    # Write the .nut data table next to the JSON: strip a trailing .json if present, then
    # add .nut. So foo.scenario.json -> foo.scenario.nut, foo.json -> foo.nut.
    base = out_path[:-len(".json")] if out_path.endswith(".json") else out_path
    nut_path = base + ".nut"
    with open(nut_path, "w") as f:
        f.write(scen.to_nut())

    routed, total = rr.coverage()
    print(f"wrote {out_path}")
    print(f"wrote {nut_path}")
    print(f"cells placed: {len(scen.cells)}")
    print(f"routes: {len(scen.routes)}  nets routed: {routed}/{total}")
    if rr.unrouted:
        print(f"UNROUTED nets ({len(rr.unrouted)}):")
        for u in rr.unrouted:
            print(f"  {u.net}: {u.source} -> {u.target}  ({u.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv))
