"""Amaranth primitive cells describing the OpenTTD substrate gate set.

These mirror the cell types in synth/netlist.py CELL_LIBRARY. On the substrate the
only physically built gate is NOR (universal), and NOT is a one input NOR. The rest are
convenience cells that synthesis lowers back to NOR. We describe the same primitives here
in Amaranth so the HDL frontend and the netlist interchange format agree on what a gate is.

Everything here is pure combinational. There is no clock and no state. A net is one bit,
train present == 1 on the real substrate.

The cells are small Elaboratables with explicit input and output Signals so they can be
instantiated, simulated, or elaborated independently. They are not strictly required to
build the structural adder (which is emitted straight to a Netlist), but they document the
primitive set in Amaranth form and give the simulator something concrete to check.
"""

from __future__ import annotations

from amaranth.hdl import Elaboratable, Module, Signal


class Nor(Elaboratable):
    """Variadic NOR. out = NOT(in0 OR in1 OR ...). The one buildable substrate gate.

    With width == 1 this is a plain inverter, which is exactly how NOT is built on the
    substrate (a one input NOR costs the same tile).
    """

    def __init__(self, width: int = 2):
        if width < 1:
            raise ValueError("Nor needs at least one input")
        self.width = width
        self.inputs = [Signal(name=f"in{i}") for i in range(width)]
        self.out = Signal()

    def elaborate(self, platform):
        m = Module()
        acc = self.inputs[0]
        for s in self.inputs[1:]:
            acc = acc | s
        m.d.comb += self.out.eq(~acc)
        return m


class Not(Elaboratable):
    """Inverter. out = NOT(a). Built as a one input NOR on the substrate."""

    def __init__(self):
        self.a = Signal()
        self.out = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.out.eq(~self.a)
        return m


class Buf(Elaboratable):
    """Buffer. out = a. Two inversions on the substrate (NOT of NOT)."""

    def __init__(self):
        self.a = Signal()
        self.out = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.out.eq(self.a)
        return m


class And(Elaboratable):
    """Variadic AND. Convenience cell, lowered to NOR by synthesis."""

    def __init__(self, width: int = 2):
        if width < 1:
            raise ValueError("And needs at least one input")
        self.width = width
        self.inputs = [Signal(name=f"in{i}") for i in range(width)]
        self.out = Signal()

    def elaborate(self, platform):
        m = Module()
        acc = self.inputs[0]
        for s in self.inputs[1:]:
            acc = acc & s
        m.d.comb += self.out.eq(acc)
        return m


class Or(Elaboratable):
    """Variadic OR. Convenience cell, lowered to NOR by synthesis."""

    def __init__(self, width: int = 2):
        if width < 1:
            raise ValueError("Or needs at least one input")
        self.width = width
        self.inputs = [Signal(name=f"in{i}") for i in range(width)]
        self.out = Signal()

    def elaborate(self, platform):
        m = Module()
        acc = self.inputs[0]
        for s in self.inputs[1:]:
            acc = acc | s
        m.d.comb += self.out.eq(acc)
        return m


class Xor2(Elaboratable):
    """Two input XOR. The XOR is a 5 NOR construction once lowered, see netlist.py."""

    def __init__(self):
        self.a = Signal()
        self.b = Signal()
        self.out = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.out.eq(self.a ^ self.b)
        return m
