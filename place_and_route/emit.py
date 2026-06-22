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
from channel_route import route_nets, RouteResult


# Margin of empty tiles kept around the placed logic on the right/bottom for IO + routing.
RIGHT_MARGIN = 6
BOTTOM_MARGIN = 4


def _pow2_at_least(n: int, floor: int = 64) -> int:
    """Smallest power of two >= n, clamped to a floor (OpenTTD map dims are powers of two)."""
    v = floor
    while v < n:
        v *= 2
    return v


def build_scenario(netlist: Netlist, name: str | None = None) -> tuple:
    """Place + route `netlist` into a Scenario. Returns (Scenario, RouteResult).

    The channel router (channel_route.route_nets) WIDENS the placement in place and reports
    the true routed extent and the final IO pad tiles, so we route first and size the map to
    the routed extent afterwards. Input pads sit on the left edge (x = 0); output pads land
    just past the widened logic (the router places them there and runs their risers out). The
    RouteResult is returned alongside so callers (tests, CLI) can report coverage, bridges and
    any unrouted nets honestly.
    """
    netlist.validate()
    placement = place_cells(netlist)

    # Provisional pad rows: input pads down the left edge, output pads one per row. The router
    # remaps the x of every pad into its widened coordinate system and returns the final tiles.
    in_pads: Dict[str, tuple] = {}
    for i, port in enumerate(netlist.ports.inputs):
        in_pads[port] = (0, i)
    out_pads: Dict[str, tuple] = {}
    for j, port in enumerate(netlist.ports.outputs):
        out_pads[port] = (placement.width_tiles + 1, j)

    # Clock-distribution source pads: every clock net that is NOT already a primary input pad
    # gets its own left-edge source (the clock origin). A clock that IS a primary input (the
    # common case, e.g. "clk") is sourced from its input pad, and the router fans it out to every
    # register's clock pin via that net's trunk row (the clock spine). Either way the clock net
    # reaches every register tile.
    clk_pads: Dict[str, tuple] = {}
    primary = set(netlist.ports.inputs)
    for k, clk in enumerate(netlist.clocks()):
        if clk not in primary:
            clk_pads[clk] = (0, len(in_pads) + k)

    rr: RouteResult = route_nets(netlist, placement, placement.width_tiles + 1,
                                 placement.height_tiles,
                                 input_pads=in_pads, output_pads=out_pads,
                                 clock_pads=clk_pads)

    # Final pad tiles come back from the router (widened coordinates).
    input_pads = rr.input_pads or in_pads
    output_pads = rr.output_pads or out_pads
    clock_pads = rr.clock_pads or clk_pads

    # Size the map to cover everything the router used (logic, risers, trunk band, pads).
    need_w = max(rr.width_tiles, placement.width_tiles) + RIGHT_MARGIN
    need_h = max(rr.height_tiles, placement.height_tiles) + BOTTOM_MARGIN
    for (px, py) in (list(input_pads.values()) + list(output_pads.values())
                     + list(clock_pads.values())):
        need_w = max(need_w, px + 1 + RIGHT_MARGIN)
        need_h = max(need_h, py + 1 + BOTTOM_MARGIN)
    map_w, map_h = _pow2_at_least(need_w), _pow2_at_least(need_h)

    io: List[IOPad] = []
    for port in netlist.ports.inputs:
        px, py = input_pads[port]
        io.append(IOPad(port=port, net=port, x=px, y=py, kind="input"))
    fb_pixels: List[str] = []
    out_x = 0
    for port in netlist.ports.outputs:
        px, py = output_pads[port]
        io.append(IOPad(port=port, net=port, x=px, y=py, kind="output"))
        fb_pixels.append(port)
        out_x = px
    # Clock source pads that are NOT primary inputs get a "clock" IO pad recording the clock
    # origin tile, so the scenario carries where the clock-distribution net starts.
    for net, (px, py) in clock_pads.items():
        io.append(IOPad(port=net, net=net, x=px, y=py, kind="clock"))

    framebuffer = None
    if fb_pixels:
        # Output pads share a column (the router lines them up at out_x), one row per pixel.
        fb_y0 = min(output_pads[p][1] for p in netlist.ports.outputs)
        framebuffer = Framebuffer(
            origin_x=out_x, origin_y=fb_y0, w=1, h=len(fb_pixels),
            pixel_nets=fb_pixels)

    # Clock origin: where the clock-distribution net is sourced. Prefer an explicit clock source
    # pad; else, if a clock net is a primary input (the usual "clk"), use that input pad's tile;
    # else fall back to the bottom-left corner. This pins the spine's start tile honestly.
    clk_origin = (0, map_h - 1)
    clocks = netlist.clocks()
    if clock_pads:
        clk_origin = next(iter(clock_pads.values()))
    elif clocks and clocks[0] in input_pads:
        clk_origin = input_pads[clocks[0]]

    scen = Scenario(
        name=name or netlist.name,
        map_x=map_w, map_y=map_h,
        clock=Clock(period_ticks=8, origin_x=clk_origin[0], origin_y=clk_origin[1]),
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

    # Place-and-route operates on the buildable {NOR, CONST0, CONST1} set, plus DFF register
    # tiles for a sequential design. If the input netlist still has high-level gates, lower it
    # first so placement only sees buildables. A sequential netlist (with DFFs) is lowered with
    # keep_registers=True, so its combinational logic becomes NOR while each register stays one
    # placeable register tile (and the clock-distribution net reaches every such tile).
    buildable = {"NOR", "CONST0", "CONST1", "DFF"}
    if any(c.type not in buildable for c in netlist.cells):
        netlist = netlist.to_nor(keep_registers=netlist.is_sequential())

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
