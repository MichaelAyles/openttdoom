"""Sequential circuits end to end: behavioural Amaranth m.d.sync down to a NOR + register
netlist, the counterpart of hdl/adder.py for clocked logic.

hdl/adder.py is 100 percent combinational. This module is the sequential extension the brief
asks for: an Amaranth m.d.sync design (clocked registers) lowered to a Netlist built on the
DFF register cell in synth/netlist.py, and a tool-free STRUCTURAL builder that needs no yosys.

Two worked examples, each in the same three views as the adder:

  1. A 1-bit TOGGLE flip-flop (T flip-flop): q := NOT q every rising edge. It divides the
     clock by two, the simplest possible feedback register.

  2. An n-bit up COUNTER with an enable: q := (q + 1) mod 2^n while en is high, else hold.
     This is the smallest design that exercises BOTH registers AND combinational logic in a
     feedback loop (the incrementer reads the register outputs and feeds the register inputs),
     so it is the real test that the m.d.sync -> register-netlist path closes.

The three views per example:

  view 1  behavioural Amaranth (Toggle / Counter, m.d.sync). The golden reference, simulated
          with amaranth.sim over several clock cycles.
  view 2  a STRUCTURAL gate + DFF Netlist (build_toggle_ff / build_counter) built by hand from
          NetlistBuilder, using b.dff() for the registers. Tool-free, no yosys. Lowers cleanly
          to {NOR, CONST0, CONST1} plus latch feedback via .to_nor() and is stepped with SeqSim.
  view 3  a plain Python reference (toggle_reference / counter_reference) computing the same
          state sequence, used by the tests as the ground truth both other views are checked
          against. This mirrors alu8_reference in hdl/alu.py.

Equivalence is checked with synth.netlist.sequential_equivalent (output AND state traces match
cycle for cycle over an input trace), the sequential analogue of equivalent().

There is ALSO an optional real-yosys path (synth/yosys_seq.py): yosys emits $_DFF_P_ cells for
m.d.sync registers and they techmap to the DFF register cell. It is OPTIONAL and skips cleanly
when yosys is absent; the structural path here is the verified default.

Ports
-----
  toggle:   inputs  clk            outputs q
  counter:  inputs  clk, en        outputs q0 .. q{n-1}   (q0 == least significant)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from amaranth.hdl import Elaboratable, Module, Signal

from netlist import Netlist, NetlistBuilder


# --- view 3: plain Python golden references ---------------------------------------

def toggle_reference(cycles: int, reset: int = 0) -> List[int]:
    """The toggle flip-flop output for `cycles` rising edges, starting from `reset`.

    A T flip-flop inverts its stored bit every edge, so the output strictly alternates. The
    returned list is the value VISIBLE AFTER each edge: out[k] is q after edge k (k from 0).
    """
    q = reset & 1
    out = []
    for _ in range(cycles):
        q ^= 1                     # toggle on the edge
        out.append(q)
    return out


def counter_reference(en_trace: List[int], width: int = 2,
                      reset: int = 0) -> List[int]:
    """The up-counter output after each edge, given a per-cycle enable trace.

    en_trace[k] is the enable presented for cycle k. After edge k the counter holds
    (q + en) mod 2^width, i.e. it increments by one when enabled and holds when not. The
    returned list is q after each edge (the value visible from that edge onward).
    """
    mask = (1 << width) - 1
    q = reset & mask
    out = []
    for en in en_trace:
        if en & 1:
            q = (q + 1) & mask
        out.append(q)
    return out


# --- view 1: behavioural Amaranth (m.d.sync) --------------------------------------

class Toggle(Elaboratable):
    """A 1-bit toggle (T) flip-flop: q := NOT q on every rising clock edge.

    Clocked with the default sync domain (m.d.sync), so amaranth infers a register. Divides
    the clock by two. The reset value of q is 0 (the sync domain reset).
    """

    def __init__(self):
        self.q = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.q.eq(~self.q)
        return m


class Counter(Elaboratable):
    """An n-bit up counter with enable: q := (q + 1) mod 2^n while en, else hold.

    Clocked with m.d.sync, so amaranth infers the n register bits and the increment is
    combinational logic between them. Reset value 0. This is the design that proves the
    sequential path handles a register that feeds combinational logic that feeds it back.
    """

    def __init__(self, width: int = 2):
        if width < 1:
            raise ValueError("Counter needs at least one bit")
        self.width = width
        self.en = Signal()
        self.q = Signal(width)

    def elaborate(self, platform):
        m = Module()
        with m.If(self.en):
            m.d.sync += self.q.eq(self.q + 1)
        return m


# --- view 2: structural gate + DFF Netlist (the verified, tool-free path) ----------

def build_toggle_ff() -> Netlist:
    """The toggle flip-flop as a structural Netlist: q = DFF(NOT q, clk).

    A single register whose data input is the inverse of its own output, so it flips every
    edge. The feedback (D depends on Q) is exactly what to_nor() pre-reserves the Q net for,
    so this lowers cleanly to an all-NOR master-slave latch with the cross-coupling feedback.
    """
    b = NetlistBuilder("toggle")
    clk = b.declare_input("clk")
    nq = b.fresh_net()                     # will carry NOT q
    q = b.dff(nq, clk)                     # q = DFF(nq, clk)
    b.nor_into([q], nq)                    # nq = NOR(q) = NOT q  (closes the feedback)
    b.alias_output("q", q)
    return b.finish()


def build_counter(width: int = 2) -> Netlist:
    """An n-bit up counter with enable, as a structural gate + DFF Netlist.

    Each bit is a register q[i] = DFF(q_next[i], clk). The next-state logic is a ripple
    incrementer gated by en:

        carry[0]   = en
        q_next[i]  = q[i] XOR carry[i]
        carry[i+1] = q[i] AND carry[i]

    so while en is high the register value increments by one each edge (binary ripple add of
    1), and while en is low carry[0] = 0 makes every q_next[i] = q[i], i.e. the counter holds.
    The register outputs q[i] feed the incrementer which feeds the register inputs, a genuine
    state-to-logic-to-state feedback loop, which to_nor() lowers by pre-reserving each Q net.

    Built only from NetlistBuilder emitters (xor2, and_) plus b.dff_into() for the
    feedback registers, so it lowers to {NOR, CONST0, CONST1} plus the latch feedback
    via .to_nor().
    """
    if width < 1:
        raise ValueError("counter needs at least one bit")
    b = NetlistBuilder("counter")
    clk = b.declare_input("clk")
    en = b.declare_input("en")

    # Reserve each register's Q net up front so the incrementer can reference q[i] before the
    # DFF that drives it is emitted (the state-feedback loop).
    q = [b.fresh_net() for _ in range(width)]

    carry = en
    for i in range(width):
        q_next = b.xor2(q[i], carry)        # bit i flips when the carry into it is 1
        carry = b.and_([q[i], carry])       # carry out of bit i
        # q[i] = DFF(q_next, clk) driving the reserved net q[i].
        b.dff_into(q_next, clk, q[i])
        b.alias_output(f"q{i}", q[i])

    return b.finish()


# --- view 3b: optional real-yosys cross-check (delegated, skips when absent) -------

def synth_counter_via_yosys(width: int = 2):
    """Optional: synthesise the behavioural Counter through a real yosys to a DFF + NOR
    netlist. Returns the imported Netlist, or raises RuntimeError if no yosys is reachable.

    Delegates to synth/yosys_seq.py so the yosys plumbing lives next to the other yosys code.
    The structural build_counter above is the verified, tool-free path; this is the optional
    "proper synthesis" cross-check, mirroring synth_adder4_via_yosys for sequential logic.
    """
    from yosys_seq import synth_counter_yosys
    res = synth_counter_yosys(width)
    if res is None:
        raise RuntimeError("no usable yosys binary for the sequential techmap")
    nl, _path = res
    return nl
