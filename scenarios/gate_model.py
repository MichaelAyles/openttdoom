"""Software model of the INTENDED clocked logic of an OpenTTD NOR tile.

What this is
------------
A tiny cycle-accurate model of how we INTEND the train-and-signal NOR gate to
behave. The substrate is a synchronous clocked design: a clock train runs a
fixed loop, and once per lap it produces a clock edge. On each edge the gate
samples its input bits, and the NOR of those inputs appears on the gate output
at the NEXT edge. That one cycle of latency is the register behaviour every
clocked gate has, and it is what makes a chain of gates settle predictably
instead of racing.

What this is NOT
----------------
This file does NOT prove that OpenTTD realises these semantics. It is a
specification of the target behaviour, written in Python so we can test the
toolchain and the timing assumptions independently of the game. The real
track-and-signal construction is the open research problem documented in
scenarios/GATE_DESIGN.md and STUCK.md. Treat the numbers here (one edge of
latency) as the contract the eventual OpenTTD build must meet, not as a
measurement of it.

Bit encoding (per GATE_DESIGN.md): on the substrate a net's value is carried by
train presence sampled at a clock edge, present == 1. Here we model that as a
plain integer 0/1 per net, advanced one clock edge at a time.

stdlib only, so tests and other modules can import it freely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence


def nor(bits: Sequence[int]) -> int:
    """Pure combinational NOR of one or more bits. 1 iff every input is 0."""
    return 0 if any(b & 1 for b in bits) else 1


@dataclass
class NorTile:
    """One clocked NOR tile.

    A tile has named input nets and a single output net. It holds the output
    value in a register. On each clock edge it computes NOR of the inputs that
    were stable BEFORE this edge, and latches that into the register, which
    becomes visible as the output from this edge onward. This is the classic
    sample-then-present register pipeline: the value you read on the output at
    edge N is NOR of the inputs as of edge N-1.

    NOT is just a one-input NOR tile, which is why the brief treats NOT and NOR
    as the same physical tile.
    """

    name: str
    inputs: List[str]
    output: str
    # the latched output bit, visible on the wire right now.
    state: int = 1   # NOR of "no high inputs" is 1, a sensible reset value.

    def sample_and_latch(self, net_values: Dict[str, int]) -> int:
        """Read inputs from the current net snapshot and latch NOR into state.

        Returns the new latched state. The caller is responsible for only
        making this visible to downstream tiles on the NEXT edge (see
        ClockedNetwork.step), which is what gives the one-cycle latency.
        """
        bits = [net_values[n] & 1 for n in self.inputs]
        self.state = nor(bits)
        return self.state


@dataclass
class ClockedNetwork:
    """A set of NOR tiles wired together, advanced one clock edge per step().

    Primary inputs are driven externally (the input pads). Every other net is
    driven by exactly one tile's output. On each edge:

      1. Take a snapshot of all net values as they are RIGHT NOW.
      2. Every tile samples that snapshot and latches its new output.
      3. The latched outputs become the visible net values for the next edge.

    Step 1 reading the OLD snapshot is the whole point: it models registered
    (clocked) gates, so a tile reacts to last edge's inputs, not this edge's
    freshly-changing ones. A combinational ripple would instead recompute
    within a single edge. We deliberately do NOT do that, because the train
    substrate cannot settle a long combinational chain inside one clock lap.
    """

    tiles: List[NorTile] = field(default_factory=list)
    primary_inputs: List[str] = field(default_factory=list)
    # current visible value of every net.
    nets: Dict[str, int] = field(default_factory=dict)
    edges: int = 0

    def reset(self, input_values: Dict[str, int]) -> None:
        """Initialise nets. Primary inputs take the given values, tile outputs
        take their register reset value."""
        self.edges = 0
        self.nets = {}
        for n in self.primary_inputs:
            self.nets[n] = input_values.get(n, 0) & 1
        for t in self.tiles:
            self.nets[t.output] = t.state

    def drive(self, input_values: Dict[str, int]) -> None:
        """Update primary input pads. Visible immediately, sampled next edge."""
        for n, v in input_values.items():
            if n not in self.primary_inputs:
                raise KeyError(f"{n} is not a primary input")
            self.nets[n] = v & 1

    def step(self) -> None:
        """Advance exactly one clock edge."""
        snapshot = dict(self.nets)              # 1. freeze current values
        latched = {}
        for t in self.tiles:                    # 2. every tile samples the snapshot
            latched[t.output] = t.sample_and_latch(snapshot)
        for net, val in latched.items():        # 3. publish for the next edge
            self.nets[net] = val
        self.edges += 1

    def run(self, cycles: int) -> None:
        for _ in range(cycles):
            self.step()

    def value(self, net: str) -> int:
        return self.nets[net]

    def settle(self, max_cycles: int = 64) -> int:
        """Step until net values stop changing (a fixed point) or give up.

        For a fixed combinational function with no feedback this converges in at
        most depth+1 edges. Returns the number of edges taken. Raises if it did
        not settle, which flags an oscillator or a too-small bound.
        """
        for i in range(max_cycles):
            before = dict(self.nets)
            self.step()
            if self.nets == before:
                return i + 1
        raise RuntimeError(f"network did not settle within {max_cycles} edges")


# -- convenience builders for the two single-tile gates the brief asks about --

def single_nor(n_inputs: int = 2) -> ClockedNetwork:
    """A network that is just one NOR tile named 'g', inputs a,b,... -> out 'y'."""
    ins = [chr(ord("a") + i) for i in range(n_inputs)]
    tile = NorTile(name="g", inputs=ins, output="y")
    return ClockedNetwork(tiles=[tile], primary_inputs=ins)


def single_not() -> ClockedNetwork:
    """A NOT gate: a one-input NOR tile. Same physical tile as NOR."""
    return single_nor(1)
