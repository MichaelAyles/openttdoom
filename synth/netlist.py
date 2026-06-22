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

Sequential elements
-------------------
The cell library also carries ONE sequential primitive, the DFF (a clocked 1-bit register,
a positive-edge-triggered D flip-flop). It is the only cell whose output depends on past
state rather than on its current inputs alone, so it is handled specially:

  - It is NOT evaluated by the combinational `simulate()` / `truth_table()` (those raise on a
    DFF, keeping the combinational contract intact). It is evaluated by the SEQUENTIAL
    stepping API (`SeqSim`), which applies inputs, pulses the clock, lets registers capture,
    and reads outputs over clock cycles.
  - `to_nor()` lowers a DFF to a master-slave pair of gated NOR D-latches built only from
    cross-coupled NOR gates, since NOR is the only buildable gate. The lowering introduces
    legal feedback loops (the cross-coupling), so the lowered netlist is sequential, not
    acyclic, and must be evaluated with `SeqSim` too. The lowering is exhaustively verified
    in the tests to reproduce the DFF's behaviour, including the one-edge latency that
    scenarios/gate_model.py specifies.

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


def _seq_eval(bits: Sequence[int]) -> int:
    # Sequential cells have no combinational eval: their output is past state, not a function
    # of the current inputs. simulate()/truth_table() reject them; SeqSim drives them. Calling
    # this is a bug (a combinational path tried to evaluate a register), so fail loudly.
    raise TypeError(
        "sequential cell has no combinational eval; step it with SeqSim, not simulate()")


@dataclass(frozen=True)
class CellType:
    name: str
    min_in: int
    max_in: int          # -1 == unbounded
    eval: Callable[[Sequence[int]], int]
    sequential: bool = False   # True for clocked memory (DFF): not combinational.


# eval functions take the list of input bits and return the output bit.
#
# DFF is the sequential primitive: a positive-edge-triggered D flip-flop. Its `inputs` list
# holds the single data input D, and the clock net is carried separately on Cell.clock (so the
# data fan-in stays a clean one-element list and the clock is not mistaken for data). On a
# rising clock edge it captures D; otherwise it holds. It has no combinational eval (see
# _seq_eval) and is driven only by SeqSim.
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
    "DFF":    CellType("DFF",    1,  1, _seq_eval, sequential=True),
}

# the only cell types that survive lowering and get built on the substrate.
BUILDABLE = {"NOR", "CONST0", "CONST1"}

# cell types whose output is clocked state, not a combinational function of their inputs.
SEQUENTIAL = {name for name, ct in CELL_LIBRARY.items() if ct.sequential}


def is_sequential(cell_type: str) -> bool:
    """True iff `cell_type` is a clocked memory primitive (DFF), not a combinational gate."""
    ct = CELL_LIBRARY.get(cell_type)
    return bool(ct and ct.sequential)


# --- data model -------------------------------------------------------------------

@dataclass
class Cell:
    id: str
    type: str
    inputs: List[str]          # input net names, in order
    output: str                # output net name
    # sequential-only fields. `clock` is the clock net for a DFF (None for combinational
    # cells); `reset` is the value a DFF's register holds before the first capturing edge.
    # Both default so existing JSON (no clock/reset keys) and existing call sites still load.
    clock: "str | None" = None
    reset: int = 0

    def is_sequential(self) -> bool:
        return is_sequential(self.type)

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
            cnets = [*c.inputs, c.output]
            if c.clock is not None:
                cnets.append(c.clock)
            for n in cnets:
                if n not in seen:
                    seen.append(n)
        for n in self.ports.outputs:
            if n not in seen:
                seen.append(n)
        return seen

    def is_sequential(self) -> bool:
        """True iff any cell is a clocked memory primitive (so the netlist needs SeqSim)."""
        return any(c.is_sequential() for c in self.cells)

    def clocks(self) -> List[str]:
        """The distinct clock nets driving the sequential cells, in first-seen order."""
        seen: List[str] = []
        for c in self.cells:
            if c.clock is not None and c.clock not in seen:
                seen.append(c.clock)
        return seen

    def combinational_cone(self) -> "Netlist":
        """Cut every register, returning the purely COMBINATIONAL cone around the DFFs.

        A sequential netlist has no static truth table (the registers carry state), so it
        cannot be compared with equivalent() directly. The standard way to compare two
        sequential designs combinationally is to CUT the registers at their boundaries: each
        DFF is removed, its output Q becomes a fresh PRIMARY INPUT (a free register-state
        variable), and its data input D and clock become PRIMARY OUTPUTS (the next-state and
        clock-fanout the logic computes). What is left is acyclic and combinational, and its
        truth table fully captures the next-state and output logic the placement must preserve.
        So equivalent(a.combinational_cone(), b.combinational_cone()) proves two sequential
        netlists realise the SAME register-transfer logic (same next-state functions, same
        outputs, same clocking), which is exactly the combinational-cone equivalence the
        place-and-route check needs for a clocked design. Raises if the cone is still cyclic
        (a combinational loop that no register breaks), which is a real design error.
        """
        regs = [c for c in self.cells if c.is_sequential()]
        reg_outputs = {c.output for c in regs}
        comb_cells = [c for c in self.cells if not c.is_sequential()]

        # New primary inputs: the existing ones plus every register output (now a free var).
        new_inputs: List[str] = list(self.ports.inputs)
        for c in regs:
            if c.output not in new_inputs:
                new_inputs.append(c.output)
        # New primary outputs: the existing ones plus every register's D and clock net (the
        # next-state and clock-fanout the cone computes). De-duplicated, stable order.
        new_outputs: List[str] = list(self.ports.outputs)
        for c in regs:
            for net in (c.inputs[0], c.clock):
                if net is not None and net not in new_outputs:
                    new_outputs.append(net)

        cone = Netlist(
            name=self.name + "_cone",
            cells=[Cell(c.id, c.type, list(c.inputs), c.output) for c in comb_cells],
            ports=Ports(inputs=new_inputs, outputs=new_outputs),
        )
        cone.validate()
        return cone

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
            # sequential cells (DFF) must have a driven clock net; combinational cells must not
            # carry one, so a stray clock on a NOR cannot be silently ignored.
            if ct.sequential:
                if c.clock is None:
                    raise ValueError(f"sequential cell {c.id} ({c.type}) has no clock net")
                if c.clock not in driven:
                    raise ValueError(
                        f"cell {c.id} clock {c.clock} is undriven (no cell or primary input)")
            elif c.clock is not None:
                raise ValueError(
                    f"combinational cell {c.id} ({c.type}) must not carry a clock net")
        for o in self.ports.outputs:
            if o not in driven:
                raise ValueError(f"primary output {o} is undriven")

    # -- simulation: the software 'golden hardware' model --
    def simulate(self, input_values: Dict[str, int]) -> Dict[str, int]:
        """Evaluate the combinational netlist. Returns every net's value.

        Cells are evaluated in dependency order. A combinational loop (no progress with
        cells still pending) raises -- this path is purely combinational. A netlist that
        contains a sequential cell (a DFF) cannot be evaluated combinationally and raises;
        step it over clock cycles with SeqSim instead.
        """
        self.validate()
        if self.is_sequential():
            seq = [c.id for c in self.cells if c.is_sequential()]
            raise ValueError(
                "netlist has sequential cells (" + ", ".join(seq) +
                "); use SeqSim to step it over clock cycles, not simulate()")
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
    def to_nor(self, keep_registers: bool = False) -> "Netlist":
        """Return an equivalent netlist using only NOR / CONST0 / CONST1 cells.

        NOT becomes a 1-input NOR (same tile). Every other gate is rebuilt from NORs. A DFF
        becomes a master-slave pair of gated NOR D-latches (see NetlistBuilder.dff_nor),
        which is pure NOR plus the cross-coupling feedback, so the lowered result is itself
        buildable. The lowering of a DFF therefore turns an acyclic logical netlist into a
        netlist with feedback loops (the latch cross-coupling), which is why a lowered
        sequential netlist is stepped with SeqSim, not simulate(). Correctness (combinational
        gates by truth table, the DFF by its sequential behaviour) is checked in the tests.

        keep_registers (the place-and-route lowering). When True, a DFF is NOT expanded into
        latches: it is kept as a single DFF cell (a REGISTER TILE) whose D and clock nets are
        the lowered NOR nets feeding it. The surrounding combinational logic still lowers to
        {NOR, CONST0, CONST1}, but each register stays one placeable tile. This is what the
        placer/router consume for a sequential design: the register is a footprint with a clock
        pin, and the clock-distribution net reaches every such tile. The result is still
        SEQUENTIAL (it has DFF cells) and is stepped with SeqSim, and it is equivalent to the
        full latch expansion on the combinational cone, which the tests check.
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
            if cell.is_sequential():
                # A DFF. Reserve and register its output net BEFORE resolving D and the
                # clock, so a feedback path (D depending on Q through combinational gates,
                # e.g. a counter) terminates at the reserved Q net instead of recursing
                # forever.
                q = b.fresh_net()
                memo[net] = q
                d = resolve(cell.inputs[0])
                clk = resolve(cell.clock)
                if keep_registers:
                    # Keep the register as one placeable DFF tile driving the reserved Q net,
                    # with its data and clock now on lowered NOR nets.
                    b.dff_into(d, clk, q, reset=cell.reset)
                else:
                    # Expand into the master-slave NOR latch driving the reserved Q net.
                    b.dff_nor(d, clk, q, reset=cell.reset)
                return q
            args = [resolve(i) for i in cell.inputs]
            out = b.emit(cell.type, args)
            memo[net] = out
            return out

        # Resolve every net that drives a DFF input/clock as well, so DFFs not feeding a
        # primary output (state that only loops back) are still emitted.
        for c in self.cells:
            if c.is_sequential():
                resolve(c.output)
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

    def fresh_net(self) -> str:
        """Allocate a fresh internal net name (public so to_nor can pre-reserve a DFF Q)."""
        return self._net()

    def nor_into(self, ins: List[str], out: str) -> str:
        """Emit NOR(ins) driving the GIVEN net `out` (not a fresh one).

        Used to build cross-coupled latches whose output net was reserved up front, so the
        feedback wiring can name the latch outputs before they are driven.
        """
        self.cells.append(Cell(self._cell_id(), "NOR", list(ins), out))
        return out

    # -- the sequential primitive --
    def dff(self, d: str, clk: str, reset: int = 0) -> str:
        """Emit a high-level DFF cell (a positive-edge-triggered D flip-flop), return Q.

        `d` is the data net, `clk` the clock net. The DFF captures D on the rising clock edge
        and holds otherwise; `reset` is the value it holds before the first capturing edge.
        This is a sequential cell, so the resulting netlist is stepped with SeqSim, and
        to_nor() lowers it to the all-NOR master-slave latch built by dff_nor().
        """
        q = self._net()
        self.cells.append(Cell(self._cell_id(), "DFF", [d], q, clock=clk, reset=reset & 1))
        return q

    def dff_into(self, d: str, clk: str, q: str, reset: int = 0) -> str:
        """Emit a high-level DFF driving the GIVEN net `q` (not a fresh one), return q.

        The sequential analogue of nor_into(): used to build a register whose output net was
        reserved up front (with fresh_net) so a state-feedback path can name the register
        output before the DFF that drives it is emitted, e.g. a counter whose incrementer
        reads q[i] to compute the next-state data feeding q[i]. Also used by
        to_nor(keep_registers=True) to pre-reserve a register's Q (terminating any feedback
        loop through it) and drive it with a kept register tile. The resulting netlist is
        sequential and stepped with SeqSim; to_nor() lowers the DFF to the all-NOR master
        -slave latch (and the feedback through the incrementer becomes ordinary wiring).
        """
        self.cells.append(Cell(self._cell_id(), "DFF", [d], q, clock=clk, reset=reset & 1))
        return q

    def _gated_d_latch_nor(self, d: str, en: str, q: str, qbar: str) -> None:
        """Build an active-high gated D latch from NOR only, driving the reserved q/qbar nets.

        While en == 1 the latch is transparent (q follows d); while en == 0 it holds.
        Construction: a NOR SR latch (q = NOR(r, qbar), qbar = NOR(s, q)) fed by set/reset
        terms that are gated by the enable, s = AND(d, en), r = AND(NOT d, en). When en == 0
        both s and r are 0 so the latch holds; when en == 1 exactly one of s/r is 1 (they are
        complementary in d), so the forbidden s == r == 1 state never arises.
        """
        s = self.and_([d, en])              # set   when d=1 and enabled
        r = self.and_([self.inv(d), en])    # reset when d=0 and enabled
        # cross-coupled NOR SR latch driving the reserved q / qbar nets (the feedback).
        self.nor_into([r, qbar], q)         # q    = NOR(r, qbar)
        self.nor_into([s, q], qbar)         # qbar = NOR(s, q)

    def dff_nor(self, d: str, clk: str, q: str, reset: int = 0) -> str:
        """Build a positive-edge-triggered DFF from NOR only, driving the reserved net `q`.

        Master-slave: a master gated D-latch transparent while clk == 0 tracks d, and a slave
        gated D-latch transparent while clk == 1 passes the master's held value to q. On the
        rising edge (clk 0 -> 1) the master freezes its last d and the slave opens, so q
        becomes that frozen d. That is the one-edge-latency register behaviour: q after edge N
        is d sampled just before edge N. Built only from NOR / CONST cells (via and_/inv/
        nor_into), so the result is buildable.

        Reset / power-on state. The all-NOR latch has NO async reset line (the train substrate
        has none either), so its power-on state is whatever SeqSim's initial settle lands on,
        not necessarily the high-level DFF's `reset` value. The two forms are therefore only
        guaranteed identical AFTER real data has been clocked through the register (the
        pipeline is flushed); before that the lowered latch may differ for up to one register
        depth of cycles. This is physically honest, not a bug: a real cross-coupled-NOR latch
        comes up in an arbitrary state until first clocked. `reset` is kept on the high-level
        DFF for a defined behavioural-model start; it is not wired into the gate netlist.
        """
        notclk = self.inv(clk)              # master enable = NOT clk
        qm = self.fresh_net()               # master latch output
        qm_bar = self.fresh_net()
        self._gated_d_latch_nor(d, notclk, qm, qm_bar)
        q_bar = self.fresh_net()            # slave latch complementary output
        self._gated_d_latch_nor(qm, clk, q, q_bar)
        return q

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
        if t == "DFF":
            raise ValueError(
                "DFF is sequential and needs a clock net; use builder.dff(d, clk) "
                "or builder.dff_nor(d, clk, q), not emit()")
        raise ValueError(f"cannot lower gate type {t}")

    def finish(self) -> Netlist:
        nl = Netlist(self.name, self.cells, Ports(list(self._inputs), list(self._outputs)))
        nl.validate()
        return nl


def equivalent(a: Netlist, b: Netlist) -> bool:
    """True iff two netlists have the same primary I/O names and the same truth table.

    Port comparison is order-independent (by name), since the truth table is keyed by
    name: two netlists that compute the same function are equivalent even if a synthesis
    backend emitted the input ports in a different order.

    Combinational only: a sequential netlist (one with a DFF) has no static truth table, so
    truth_table() raises and equivalent() is not the right tool. Compare sequential netlists
    by stepping them with SeqSim over an input/clock schedule instead.
    """
    if set(a.ports.inputs) != set(b.ports.inputs):
        return False
    if set(a.ports.outputs) != set(b.ports.outputs):
        return False
    for iv, ov in a.truth_table():
        if b.outputs_for(iv) != ov:
            return False
    return True


# --- sequential simulation: stepping a netlist with registers over clock cycles -------

def simulate_trace(
    netlist: "Netlist",
    trace: "Sequence[Dict[str, int]]",
    clock: str = "clk",
    state_nets: "Sequence[str] | None" = None,
    reset_inputs: "Dict[str, int] | None" = None,
) -> "List[Dict[str, int]]":
    """Step `netlist` over an input `trace`, one full clock cycle per entry, return outputs.

    This is the sequential analogue of truth_table(): where truth_table() enumerates a
    combinational function, simulate_trace() drives a clocked netlist through a sequence of
    cycles and records what comes out. Each entry in `trace` is a dict of the (non-clock)
    primary input values to present for that cycle. For each entry we run one positive-edge
    clock_cycle(data, clock) on a SeqSim and then read every primary output. The returned list
    has one dict per cycle.

    If `state_nets` is given, those net values are also read into each cycle's dict (under
    their own net names), so a caller can compare not just the outputs but the internal
    register state cycle by cycle. For a behavioural DFF netlist the state nets are the DFF
    output nets (the register contents); for an all-NOR lowered netlist they are whatever
    nets carry the corresponding latched values. A net listed in both ports.outputs and
    state_nets is simply read once under its name.

    `reset_inputs` seeds the primary inputs at reset (default: all 0, clock 0). The clock net
    is driven by clock_cycle and need not appear in the trace entries.
    """
    sim = SeqSim(netlist)
    iv0 = {clock: 0}
    if reset_inputs:
        iv0.update(reset_inputs)
    sim.reset(iv0)
    state_nets = list(state_nets or [])
    out: List[Dict[str, int]] = []
    for cycle_inputs in trace:
        data = {k: v for k, v in cycle_inputs.items() if k != clock}
        sim.clock_cycle(data, clock=clock)
        row = dict(sim.outputs())
        for n in state_nets:
            row[n] = sim.value(n)
        out.append(row)
    return out


def sequential_equivalent(
    a: "Netlist",
    b: "Netlist",
    trace: "Sequence[Dict[str, int]]",
    clock: str = "clk",
    state_nets: "Sequence[str] | None" = None,
    skip_cycles: int = 0,
    reset_inputs: "Dict[str, int] | None" = None,
) -> bool:
    """True iff two sequential netlists produce the same output (and state) trace over `trace`.

    equivalent() compares COMBINATIONAL netlists by their full truth table. A sequential
    netlist has no static truth table (truth_table() raises on a DFF), so its behaviour is a
    function of the input HISTORY, not the current inputs alone. sequential_equivalent()
    compares two sequential netlists the honest way: it drives BOTH with the identical input
    trace, one full clock cycle per entry, and asserts their output traces are equal cycle for
    cycle. With `state_nets` it also asserts the internal register state traces are equal, a
    strictly stronger check than outputs alone.

    Both netlists must share the same primary input and output net names (order-independent),
    so the same trace drives both and the same outputs are compared. This is the natural pair
    for checking a lowering: a behavioural DFF netlist against its all-NOR to_nor() form, both
    of which keep the port names, compared over a long trace.

    skip_cycles drops the first N cycles before comparing. The all-NOR master-slave latch has
    no async reset, so it powers on in an arbitrary settled state and only matches the
    behavioural DFF AFTER real data has been clocked through (the pipeline is flushed); set
    skip_cycles to at least the register depth when comparing a behavioural netlist to its
    lowered form (see NetlistBuilder.dff_nor for why). Compare two same-level netlists, or two
    behavioural netlists with a defined reset, with skip_cycles == 0 for an exact match from
    cycle 0. For a state comparison across the two levels, pass `state_nets` that name the
    SAME nets in both (e.g. the DFF Q nets that to_nor() preserves) or compare outputs only.
    """
    if set(a.ports.inputs) != set(b.ports.inputs):
        return False
    if set(a.ports.outputs) != set(b.ports.outputs):
        return False
    ta = simulate_trace(a, trace, clock=clock, state_nets=state_nets,
                        reset_inputs=reset_inputs)
    tb = simulate_trace(b, trace, clock=clock, state_nets=state_nets,
                        reset_inputs=reset_inputs)
    return ta[skip_cycles:] == tb[skip_cycles:]


class SeqSim:
    """Cycle-stepping simulator for a netlist that contains clocked registers (DFFs).

    The combinational simulate()/truth_table() path is unchanged and stays the default for
    acyclic combinational netlists. SeqSim is the SEQUENTIAL path: it evaluates a netlist that
    has state, advancing it one clock cycle at a time. It handles BOTH levels of description:

      - a high-level netlist whose DFFs are CELL_LIBRARY 'DFF' cells (behavioural registers),
        and
      - the all-NOR netlist that to_nor() lowers those DFFs into, where each register is a
        master-slave pair of cross-coupled NOR latches (feedback loops, no DFF cells).

    Both are stepped identically through the same public API, which is the whole point: the
    lowering is verified by checking that the lowered all-NOR netlist reproduces the
    behavioural DFF netlist cycle for cycle.

    Model
    -----
    Every net holds a 0/1 value that persists between cycles (real wires do not go undefined,
    they hold their last level). A settle() relaxes the combinational logic and any latch
    feedback to a fixed point by repeated in-place evaluation, starting from the held values,
    which converges for a properly driven design and raises on an oscillator (matching
    scenarios/gate_model.py::ClockedNetwork.settle).

    Two ways to drive it:

      - Behavioural / lowered alike: drive the primary input nets yourself (including the
        clock net) and call settle(); pulse the clock by driving it 0 then 1 with a settle
        around each, exactly as hardware sees a clock edge.
      - Convenience: clock_cycle(data, clock="clk") performs one full positive-edge cycle
        (clock low, apply data, clock high, capture), which is the natural register step and
        gives the one-edge latency that gate_model.py specifies: the value clocked in on cycle
        N appears on the register output during cycle N (read after the rising edge), and a
        chain of registers advances one stage per cycle.
    """

    # generous, since a deep combinational cone plus a few latch loops still settles fast.
    DEFAULT_MAX_ITERS = 1000

    def __init__(self, netlist: Netlist):
        netlist.validate()
        self.netlist = netlist
        self.primary_inputs: List[str] = list(netlist.ports.inputs)
        # split cells into the combinational ones (evaluated by relaxation) and the
        # behavioural DFFs (state updated on a clock edge). The lowered netlist has no DFF
        # cells, so dffs is empty and the latch feedback is handled by the relaxation alone.
        self.comb_cells: List[Cell] = [c for c in netlist.cells if not c.is_sequential()]
        self.dffs: List[Cell] = [c for c in netlist.cells if c.is_sequential()]
        self.values: Dict[str, int] = {}
        # last clock level seen per DFF clock net, for rising-edge detection.
        self._prev_clk: Dict[str, int] = {}

    # -- state init --
    def reset(self, input_values: "Dict[str, int] | None" = None) -> None:
        """Initialise every net. Primary inputs take the given values (default 0), DFF
        outputs take their register reset value, and the combinational logic is settled."""
        iv = dict(input_values or {})
        self.values = {}
        for n in self.netlist.nets():
            self.values[n] = 0
        for n in self.primary_inputs:
            self.values[n] = iv.get(n, 0) & 1
        # behavioural DFF outputs start at their reset value.
        for d in self.dffs:
            self.values[d.output] = d.reset & 1
        self._prev_clk = {}
        for d in self.dffs:
            if d.clock is not None:
                self._prev_clk[d.clock] = self.values.get(d.clock, 0) & 1
        self.settle()

    # -- driving inputs --
    def set_inputs(self, input_values: Dict[str, int]) -> None:
        """Drive one or more primary input nets. Visible immediately, sampled on settle()."""
        for n, v in input_values.items():
            if n not in self.primary_inputs:
                raise KeyError(f"{n} is not a primary input of {self.netlist.name}")
            self.values[n] = v & 1

    # -- combinational relaxation to a fixed point --
    def settle(self, max_iters: int = DEFAULT_MAX_ITERS) -> int:
        """Relax the combinational cells (and any latch feedback) to a fixed point.

        In-place (Gauss-Seidel) sweeps over the combinational cells, starting from the values
        the nets already hold, so a stable latch stays put and a driven latch flips once and
        settles. DFF cells are NOT evaluated here, their output is held state. Returns the
        number of sweeps. Raises on non-convergence (an oscillator or a too-small bound),
        matching gate_model.py::ClockedNetwork.settle.
        """
        for sweep in range(1, max_iters + 1):
            changed = False
            for c in self.comb_cells:
                bits = [self.values[n] & 1 for n in c.inputs]
                nv = CELL_LIBRARY[c.type].eval(bits)
                if self.values.get(c.output) != nv:
                    self.values[c.output] = nv
                    changed = True
            if not changed:
                return sweep
        raise RuntimeError(
            f"netlist {self.netlist.name} did not settle within {max_iters} sweeps "
            "(combinational oscillator?)")

    # -- behavioural register edge --
    def _apply_dff_edges(self) -> None:
        """Capture D into each behavioural DFF whose clock just rose (0 -> 1), then hold.

        Only meaningful for the high-level netlist (DFF cells). The lowered netlist has no
        DFF cells, so this is a no-op there and its registers update purely through the latch
        feedback in settle().
        """
        captured: Dict[str, int] = {}
        for d in self.dffs:
            prev = self._prev_clk.get(d.clock, 0)
            now = self.values[d.clock] & 1
            if prev == 0 and now == 1:                 # rising edge: capture D
                captured[d.output] = self.values[d.inputs[0]] & 1
            # falling/steady edges hold (no change to the register output).
        for d in self.dffs:
            if d.clock is not None:
                self._prev_clk[d.clock] = self.values[d.clock] & 1
        for net, v in captured.items():
            self.values[net] = v

    def _pulse(self, clock: str, level: int) -> None:
        """Drive `clock` to `level`, settle, and let behavioural DFFs see the edge."""
        if clock not in self.primary_inputs:
            raise KeyError(f"clock {clock} is not a primary input of {self.netlist.name}")
        self.values[clock] = level & 1
        self.settle()
        self._apply_dff_edges()
        # settle again so a behavioural DFF's freshly captured output propagates through any
        # combinational logic feeding other nets/outputs this same phase.
        if self.dffs:
            self.settle()

    def clock_cycle(self, data: "Dict[str, int] | None" = None,
                    clock: str = "clk") -> None:
        """Run one full positive-edge clock cycle and capture.

        Sequence: drive the clock LOW and settle (so a master-slave register opens its master
        and the slave holds), apply the data inputs, then drive the clock HIGH and settle (the
        rising edge: the master freezes its sampled data and the slave passes it to the output).
        After this returns, read the register output with value(). This is exactly the one-edge
        register step gate_model.py specifies: data presented for cycle N is visible on the
        register output from this cycle's rising edge onward.
        """
        self._pulse(clock, 0)
        if data:
            self.set_inputs(data)
            self.settle()
        self._pulse(clock, 1)

    # -- readout --
    def value(self, net: str) -> int:
        return self.values[net] & 1

    def outputs(self) -> Dict[str, int]:
        return {o: self.values[o] & 1 for o in self.netlist.ports.outputs}
