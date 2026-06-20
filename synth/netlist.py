"""openttdoom gate-level netlist: the interchange format for the whole toolchain.

This is the contract that ties the pieces together. The HDL frontend (hdl/) emits a
Netlist, place-and-route (place_and_route/) consumes one, the software "golden hardware"
simulator below evaluates one, and the OpenTTD emitter stamps one onto the map.

Model
-----
A netlist is a set of cells drawn from a tiny library. Every cell has exactly one output
net and zero or more input nets. Nets are 1-bit signals. On the OpenTTD substrate a net's
value is encoded by train presence sampled at a clock edge: train present == 1.

Primary inputs and outputs are just net names listed in `ports`. Place-and-route turns
ports.inputs into input pads (pokeable tiles) and ports.outputs into output pads
(framebuffer pixels / readable tiles).

The only cell that is physically built on the substrate is NOR (universal). NOT is a
one-input NOR, so it costs the same tile. CONST0/CONST1 are tie cells (hardwired landscape).
Everything else is convenience for writing readable HDL and is removed by `to_nor()`, which
lowers a general netlist to the buildable {NOR, CONST0, CONST1} set. This mirrors what a
real synthesis flow (yosys) would do when techmapping to a single-gate cell library.

No third-party dependencies: stdlib only, so every other module and the substrate
simulator can import this safely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from itertools import product
from typing import Callable, Dict, List, Sequence, Tuple


# --- cell library -----------------------------------------------------------------

def _nor(bits: Sequence[int]) -> int:
    return 0 if any(bits) else 1


def _nand(bits: Sequence[int]) -> int:
    return 0 if all(bits) else 1


def _xor(bits: Sequence[int]) -> int:
    acc = 0
    for b in bits:
        acc ^= (b & 1)
    return acc


@dataclass(frozen=True)
class CellType:
    name: str
    min_in: int
    max_in: int          # -1 == unbounded
    eval: Callable[[Sequence[int]], int]


# eval functions take the list of input bits and return the output bit.
CELL_LIBRARY: Dict[str, CellType] = {
    "NOR":    CellType("NOR",   1, -1, _nor),
    "NOT":    CellType("NOT",   1,  1, lambda b: 1 - (b[0] & 1)),
    "BUF":    CellType("BUF",   1,  1, lambda b: b[0] & 1),
    "AND":    CellType("AND",   1, -1, lambda b: 1 if all(b) else 0),
    "OR":     CellType("OR",    1, -1, lambda b: 1 if any(b) else 0),
    "NAND":   CellType("NAND",  1, -1, _nand),
    "XOR":    CellType("XOR",   2, -1, _xor),
    "XNOR":   CellType("XNOR",  2, -1, lambda b: 1 - _xor(b)),
    "CONST0": CellType("CONST0", 0, 0, lambda b: 0),
    "CONST1": CellType("CONST1", 0, 0, lambda b: 1),
}

# the only cell types that survive lowering and get built on the substrate.
BUILDABLE = {"NOR", "CONST0", "CONST1"}


# --- data model -------------------------------------------------------------------

@dataclass
class Cell:
    id: str
    type: str
    inputs: List[str]          # input net names, in order
    output: str                # output net name

    def eval(self, values: Dict[str, int]) -> int:
        ct = CELL_LIBRARY[self.type]
        bits = [values[n] & 1 for n in self.inputs]
        return ct.eval(bits)


@dataclass
class Ports:
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)


@dataclass
class Netlist:
    name: str
    cells: List[Cell] = field(default_factory=list)
    ports: Ports = field(default_factory=Ports)

    # -- introspection --
    def nets(self) -> List[str]:
        seen = []
        for n in self.ports.inputs:
            if n not in seen:
                seen.append(n)
        for c in self.cells:
            for n in (*c.inputs, c.output):
                if n not in seen:
                    seen.append(n)
        for n in self.ports.outputs:
            if n not in seen:
                seen.append(n)
        return seen

    def driver_of(self) -> Dict[str, Cell]:
        """net name -> the cell that drives it (primary inputs have no driver)."""
        d: Dict[str, Cell] = {}
        for c in self.cells:
            if c.output in d:
                raise ValueError(f"net {c.output} driven by multiple cells")
            d[c.output] = c
        return d

    def validate(self) -> None:
        drivers = self.driver_of()
        driven = set(drivers) | set(self.ports.inputs)
        for c in self.cells:
            ct = CELL_LIBRARY.get(c.type)
            if ct is None:
                raise ValueError(f"cell {c.id}: unknown type {c.type}")
            n = len(c.inputs)
            if n < ct.min_in or (ct.max_in != -1 and n > ct.max_in):
                raise ValueError(
                    f"cell {c.id} ({c.type}): {n} inputs out of range "
                    f"[{ct.min_in}, {ct.max_in}]")
            for src in c.inputs:
                if src not in driven:
                    raise ValueError(
                        f"cell {c.id} input {src} is undriven (no cell or primary input)")
        for o in self.ports.outputs:
            if o not in driven:
                raise ValueError(f"primary output {o} is undriven")

    # -- simulation: the software 'golden hardware' model --
    def simulate(self, input_values: Dict[str, int]) -> Dict[str, int]:
        """Evaluate the combinational netlist. Returns every net's value.

        Cells are evaluated in dependency order. A combinational loop (no progress with
        cells still pending) raises -- the substrate is purely combinational for M4.
        """
        self.validate()
        values: Dict[str, int] = {}
        for n in self.ports.inputs:
            if n not in input_values:
                raise ValueError(f"missing value for primary input {n}")
            values[n] = input_values[n] & 1
        pending = list(self.cells)
        progressed = True
        while pending and progressed:
            progressed = False
            still = []
            for c in pending:
                if all(n in values for n in c.inputs):
                    values[c.output] = c.eval(values)
                    progressed = True
                else:
                    still.append(c)
            pending = still
        if pending:
            raise ValueError(
                "combinational loop or undriven net among: "
                + ", ".join(c.id for c in pending))
        return values

    def outputs_for(self, input_values: Dict[str, int]) -> Dict[str, int]:
        v = self.simulate(input_values)
        return {o: v[o] for o in self.ports.outputs}

    def truth_table(self) -> List[Tuple[Dict[str, int], Dict[str, int]]]:
        rows = []
        ins = self.ports.inputs
        for combo in product((0, 1), repeat=len(ins)):
            iv = dict(zip(ins, combo))
            rows.append((iv, self.outputs_for(iv)))
        return rows

    # -- lowering to the buildable {NOR, CONST0, CONST1} set --
    def to_nor(self) -> "Netlist":
        """Return an equivalent netlist using only NOR / CONST0 / CONST1 cells.

        NOT becomes a 1-input NOR (same tile). Every other gate is rebuilt from NORs.
        Correctness is checked elsewhere by exhaustive truth-table comparison.
        """
        b = NetlistBuilder(self.name)
        # primary inputs pass straight through as net names.
        for n in self.ports.inputs:
            b.declare_input(n)
        drivers = self.driver_of()
        memo: Dict[str, str] = {n: n for n in self.ports.inputs}

        def resolve(net: str) -> str:
            if net in memo:
                return memo[net]
            cell = drivers[net]
            args = [resolve(i) for i in cell.inputs]
            out = b.emit(cell.type, args)
            memo[net] = out
            return out

        for o in self.ports.outputs:
            res = resolve(o)
            b.alias_output(o, res)
        nl = b.finish()
        return nl

    # -- json --
    def to_json(self) -> str:
        return json.dumps({
            "name": self.name,
            "cells": [asdict(c) for c in self.cells],
            "ports": asdict(self.ports),
        }, indent=2)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())

    @staticmethod
    def from_dict(d: dict) -> "Netlist":
        return Netlist(
            name=d["name"],
            cells=[Cell(**c) for c in d["cells"]],
            ports=Ports(**d.get("ports", {})),
        )

    @staticmethod
    def load(path: str) -> "Netlist":
        with open(path) as f:
            return Netlist.from_dict(json.load(f))

    def stats(self) -> Dict[str, int]:
        s: Dict[str, int] = {}
        for c in self.cells:
            s[c.type] = s.get(c.type, 0) + 1
        s["_total_cells"] = len(self.cells)
        s["_nets"] = len(self.nets())
        return s


# --- builder ----------------------------------------------------------------------

class NetlistBuilder:
    """Helper for emitting NOR-based netlists. Used by to_nor() and by the HDL frontend.

    emit() takes a high-level gate type and a list of input net names and returns the
    net name carrying the result, generating NOR cells as needed. Output is always built
    from NOR / CONST cells only, so the result is directly buildable on the substrate.
    """

    def __init__(self, name: str):
        self.name = name
        self.cells: List[Cell] = []
        self._inputs: List[str] = []
        self._outputs: List[str] = []
        self._n = 0
        self._const: Dict[int, str] = {}

    def _net(self) -> str:
        self._n += 1
        return f"w{self._n}"

    def _cell_id(self) -> str:
        return f"g{len(self.cells)}"

    def declare_input(self, name: str) -> str:
        if name not in self._inputs:
            self._inputs.append(name)
        return name

    def alias_output(self, name: str, net: str) -> None:
        # force a net literally named `name` to carry `net`'s value, so primary output
        # names survive lowering. Two inversions == identity: name = NOT(NOT(net)).
        if net == name:
            self._outputs.append(name)
            return
        t = self.inv(net)                                          # t = NOT(net)
        self.cells.append(Cell(self._cell_id(), "NOR", [t], name))  # name = NOT(t) = net
        self._outputs.append(name)

    # -- primitive NOR emitters --
    def nor(self, ins: List[str]) -> str:
        out = self._net()
        self.cells.append(Cell(self._cell_id(), "NOR", list(ins), out))
        return out

    def inv(self, a: str) -> str:
        return self.nor([a])

    def _buf(self, a: str) -> str:
        return self.inv(self.inv(a))

    def const0(self) -> str:
        if 0 not in self._const:
            out = self._net()
            self.cells.append(Cell(self._cell_id(), "CONST0", [], out))
            self._const[0] = out
        return self._const[0]

    def const1(self) -> str:
        if 1 not in self._const:
            out = self._net()
            self.cells.append(Cell(self._cell_id(), "CONST1", [], out))
            self._const[1] = out
        return self._const[1]

    def or_(self, ins: List[str]) -> str:
        # OR(x...) = NOT(NOR(x...))
        return self.inv(self.nor(ins))

    def and_(self, ins: List[str]) -> str:
        # AND(x...) = NOR(NOT x...)   (De Morgan)
        return self.nor([self.inv(x) for x in ins])

    def nand(self, ins: List[str]) -> str:
        return self.inv(self.and_(ins))

    def xor2(self, a: str, b: str) -> str:
        # 5-NOR XOR: t4 = XNOR(a,b); xor = NOT(t4)
        return self.inv(self.xnor2(a, b))

    def xnor2(self, a: str, b: str) -> str:
        t1 = self.nor([a, b])
        t2 = self.nor([a, t1])
        t3 = self.nor([b, t1])
        return self.nor([t2, t3])   # = XNOR(a,b)

    def xor(self, ins: List[str]) -> str:
        acc = ins[0]
        for x in ins[1:]:
            acc = self.xor2(acc, x)
        return acc

    def emit(self, gate_type: str, ins: List[str]) -> str:
        """Map a CELL_LIBRARY gate type to NOR cells, return result net."""
        t = gate_type
        if t == "NOR":
            return self.nor(ins)
        if t in ("NOT",):
            return self.inv(ins[0])
        if t == "BUF":
            return self._buf(ins[0])
        if t == "OR":
            return self.or_(ins)
        if t == "AND":
            return self.and_(ins)
        if t == "NAND":
            return self.nand(ins)
        if t == "XOR":
            return self.xor(ins)
        if t == "XNOR":
            return self.inv(self.xor(ins))
        if t == "CONST0":
            return self.const0()
        if t == "CONST1":
            return self.const1()
        raise ValueError(f"cannot lower gate type {t}")

    def finish(self) -> Netlist:
        nl = Netlist(self.name, self.cells, Ports(list(self._inputs), list(self._outputs)))
        nl.validate()
        return nl


def equivalent(a: Netlist, b: Netlist) -> bool:
    """True iff two netlists have identical primary I/O and the same truth table."""
    if a.ports.inputs != b.ports.inputs or a.ports.outputs != b.ports.outputs:
        return False
    for iv, ov in a.truth_table():
        if b.outputs_for(iv) != ov:
            return False
    return True
