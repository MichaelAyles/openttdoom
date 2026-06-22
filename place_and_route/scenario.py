"""openttdoom placed-scenario schema: the hand-off from place-and-route to OpenTTD.

A Scenario is a fully spatial description of a netlist realised on the OpenTTD map:
every cell has a footprint and a position, every net is a routed track path, and the
primary inputs/outputs are pads at known tiles. The OpenTTD emitter turns this into a
GameScript data table (a .nut file) that the GameScript reads on load to stamp track,
signals and trains.

Coordinate system: OpenTTD tile coordinates (x, y), integers, origin at map corner.
Tiles are 1x1. A cell occupies a w x h footprint with its origin at (x, y). Pins are
absolute tile coordinates where a net enters/leaves a cell.

This module is schema + (de)serialisation only. place.py / route.py / emit.py fill it in.
stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

Coord = Tuple[int, int]


@dataclass
class Pin:
    net: str
    x: int
    y: int


@dataclass
class PlacedCell:
    id: str
    type: str                 # NOR / CONST0 / CONST1 (buildable set), or DFF (register tile)
    x: int                    # footprint origin
    y: int
    w: int
    h: int
    inputs: List[Pin] = field(default_factory=list)
    output: Optional[Pin] = None
    # Register-only fields. A DFF (clocked register) tile carries its clock net on a dedicated
    # CLOCK pin (kept off the data `inputs` so the data fan-in stays a clean one-element list,
    # exactly mirroring Cell.clock in the netlist), plus the reset value the register holds
    # before its first capturing edge. Both default so combinational cells and pre-register
    # scenario JSON (no clock/reset keys) still load unchanged.
    clock: Optional[Pin] = None
    reset: int = 0

    def occupied(self) -> List[Coord]:
        return [(self.x + dx, self.y + dy)
                for dx in range(self.w) for dy in range(self.h)]

    def is_register(self) -> bool:
        """True iff this is a clocked register tile (carries a clock pin)."""
        return self.clock is not None


@dataclass
class Route:
    net: str
    path: List[Coord] = field(default_factory=list)   # ordered tiles forming the track
    # Tiles where THIS net is the one carried OVER a perpendicular crossing (a bridge). At
    # a bridge tile two nets share the tile legally: one passes straight through underneath
    # (the ground net) and one is carried over on a bridge (this net, when the tile is in
    # its bridges list). Exactly one of the two crossing nets records the tile here. Old
    # scenario JSON without this field still loads (defaults to no bridges).
    bridges: List[Coord] = field(default_factory=list)


@dataclass
class IOPad:
    port: str                 # primary input/output name
    net: str
    x: int
    y: int
    kind: str                 # "input" or "output"


@dataclass
class Framebuffer:
    origin_x: int
    origin_y: int
    w: int
    h: int
    # net name driving each pixel, row-major; "" means unmapped/const-0.
    pixel_nets: List[str] = field(default_factory=list)


@dataclass
class Clock:
    period_ticks: int = 8     # train loop length -> one clock edge per lap
    origin_x: int = 0
    origin_y: int = 0


@dataclass
class Scenario:
    name: str
    map_x: int = 256
    map_y: int = 256
    clock: Clock = field(default_factory=Clock)
    cells: List[PlacedCell] = field(default_factory=list)
    routes: List[Route] = field(default_factory=list)
    io: List[IOPad] = field(default_factory=list)
    framebuffer: Optional[Framebuffer] = None

    # -- introspection --
    def input_pads(self) -> List[IOPad]:
        return [p for p in self.io if p.kind == "input"]

    def output_pads(self) -> List[IOPad]:
        return [p for p in self.io if p.kind == "output"]

    def occupied_tiles(self) -> Dict[Coord, str]:
        """tile -> owner id, for overlap checks. Cells and routes both claim tiles."""
        owner: Dict[Coord, str] = {}
        for c in self.cells:
            for t in c.occupied():
                owner[t] = c.id
        return owner

    # -- json --
    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())

    @staticmethod
    def from_dict(d: dict) -> "Scenario":
        cells = []
        for c in d.get("cells", []):
            ins = [Pin(**p) for p in c.get("inputs", [])]
            out = Pin(**c["output"]) if c.get("output") else None
            # Register tiles carry a clock pin and a reset value; both default for old JSON.
            clk = Pin(**c["clock"]) if c.get("clock") else None
            cells.append(PlacedCell(
                id=c["id"], type=c["type"], x=c["x"], y=c["y"],
                w=c["w"], h=c["h"], inputs=ins, output=out,
                clock=clk, reset=c.get("reset", 0)))
        routes = [Route(net=r["net"], path=[tuple(t) for t in r.get("path", [])],
                        bridges=[tuple(t) for t in r.get("bridges", [])])
                  for r in d.get("routes", [])]
        io = [IOPad(**p) for p in d.get("io", [])]
        fb = Framebuffer(**d["framebuffer"]) if d.get("framebuffer") else None
        clock = Clock(**d.get("clock", {}))
        return Scenario(
            name=d["name"], map_x=d.get("map_x", 256), map_y=d.get("map_y", 256),
            clock=clock, cells=cells, routes=routes, io=io, framebuffer=fb)

    @staticmethod
    def load(path: str) -> "Scenario":
        with open(path) as f:
            return Scenario.from_dict(json.load(f))

    def to_nut(self) -> str:
        """Emit the scenario as a Squirrel data table for the GameScript to consume.

        Produces `GetScenarioData()` returning a table the GameScript walks to build the
        map. Kept deliberately flat (numbers, strings, arrays) so the GS reader is trivial.
        """
        def arr(items):
            return "[" + ", ".join(items) + "]"

        lines = []
        lines.append("// AUTO-GENERATED by place_and_route/emit.py. Do not edit by hand.")
        lines.append("function GetScenarioData() {")
        lines.append("  return {")
        lines.append(f'    name = "{self.name}",')
        lines.append(f"    map_x = {self.map_x}, map_y = {self.map_y},")
        lines.append(f"    clock = {{ period = {self.clock.period_ticks}, "
                     f"x = {self.clock.origin_x}, y = {self.clock.origin_y} }},")
        cell_strs = []
        for c in self.cells:
            ins = arr([f"{{net=\"{p.net}\", x={p.x}, y={p.y}}}" for p in c.inputs])
            out = ("null" if c.output is None
                   else f"{{net=\"{c.output.net}\", x={c.output.x}, y={c.output.y}}}")
            clk = ("null" if c.clock is None
                   else f"{{net=\"{c.clock.net}\", x={c.clock.x}, y={c.clock.y}}}")
            cell_strs.append(
                f'{{id="{c.id}", type="{c.type}", x={c.x}, y={c.y}, '
                f"w={c.w}, h={c.h}, inputs={ins}, output={out}, "
                f"clock={clk}, reset={c.reset}}}")
        lines.append("    cells = " + arr(cell_strs) + ",")
        route_strs = []
        for r in self.routes:
            pts = arr([f"[{x}, {y}]" for (x, y) in r.path])
            brs = arr([f"[{x}, {y}]" for (x, y) in r.bridges])
            route_strs.append(f'{{net="{r.net}", path={pts}, bridges={brs}}}')
        lines.append("    routes = " + arr(route_strs) + ",")
        io_strs = [f'{{port="{p.port}", net="{p.net}", x={p.x}, y={p.y}, '
                   f'kind="{p.kind}"}}' for p in self.io]
        lines.append("    io = " + arr(io_strs) + ",")
        if self.framebuffer:
            fb = self.framebuffer
            px = arr([f'"{n}"' for n in fb.pixel_nets])
            lines.append(
                f"    framebuffer = {{ x={fb.origin_x}, y={fb.origin_y}, "
                f"w={fb.w}, h={fb.h}, pixels={px} }},")
        else:
            lines.append("    framebuffer = null,")
        lines.append("  }")
        lines.append("}")
        return "\n".join(lines)
