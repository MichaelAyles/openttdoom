"""The CHIP-8 8XY_ ALU, as a real circuit through the whole openttdoom pipeline.

This is Track B: it turns the 4-bit-adder toolchain demo into an actual piece of the
target machine. CHIP-8's arithmetic and logic ops all live in the 8XY_ family: they take
two 8-bit registers VX and VY, write the result back to VX, and write a flag to VF.

Three views of the same circuit, mirroring hdl/adder.py:

  1. Alu8: a behavioural Amaranth module (inputs vx[8], vy[8], op[4]; outputs result[8],
     vf). This is the golden reference, simulated with amaranth.sim in the tests.

  2. build_alu8_netlist(): a STRUCTURAL gate-level Alu8 built by hand from the
     NetlistBuilder in netlist.py. It reuses the full-adder pattern for ADD/SUB/SUBN and
     selects the per-op result with an 8-way one-hot mux. It lowers cleanly to the
     buildable {NOR, CONST0, CONST1} set via .to_nor().

  3. alu8_reference(): a plain Python reference implementing each op exactly as
     golden/chip8.py::_arith does, used by the tests as the ground truth that both the
     Amaranth module and the structural netlist are checked against.

The 8XY_ ops (op is the low nibble of the opcode), with the classic quirk defaults
(shift uses VY, vf_reset on the logic ops), matching golden/chip8.py:

    op   name   result               vf
    0x0  LD     VY                   unchanged   (we define 0 here, see note)
    0x1  OR     VX | VY              0           (vf_reset quirk)
    0x2  AND    VX & VY              0           (vf_reset quirk)
    0x3  XOR    VX ^ VY              0           (vf_reset quirk)
    0x4  ADD    (VX + VY) & 0xFF     carry out of bit 7
    0x5  SUB    (VX - VY) & 0xFF     1 if VX >= VY   (NOT borrow)
    0x6  SHR    VY >> 1              VY & 1         (lost bit)
    0x7  SUBN   (VY - VX) & 0xFF     1 if VY >= VX   (NOT borrow)
    0xE  SHL    (VY << 1) & 0xFF     VY >> 7        (lost bit)

Note on LD's VF: real CHIP-8 leaves VF unchanged on 8XY0, but this ALU is a pure
combinational function of (vx, vy, op) with no prior-state input, so "unchanged" is not
expressible. We define VF = 0 for LD. The reference, the Amaranth module and the netlist
all agree on VF = 0 for LD, so the three views stay exactly equivalent. The instruction
decoder in a full datapath would simply not write VF back for 8XY0, leaving it alone; this
ALU's vf output is a don't-care for that op and we pin it to 0 for determinism.

The unassigned codes 0x8..0xD and 0xF select nothing in the mux, so result and vf are 0
for them. The tests only exercise the nine defined ops.

Ports of the structural netlist:
    inputs  : vx0..vx7, vy0..vy7, op0..op3      (bit 0 == least significant)
    outputs : r0..r7, vf
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from amaranth.hdl import Cat, Const, Elaboratable, Module, Signal

from netlist import Netlist, NetlistBuilder


# the nine defined op codes (low nibble of the 8XY_ opcode).
OP_LD = 0x0
OP_OR = 0x1
OP_AND = 0x2
OP_XOR = 0x3
OP_ADD = 0x4
OP_SUB = 0x5
OP_SHR = 0x6
OP_SUBN = 0x7
OP_SHL = 0xE

DEFINED_OPS = (OP_LD, OP_OR, OP_AND, OP_XOR, OP_ADD, OP_SUB, OP_SHR, OP_SUBN, OP_SHL)

OP_NAME = {
    OP_LD: "LD", OP_OR: "OR", OP_AND: "AND", OP_XOR: "XOR", OP_ADD: "ADD",
    OP_SUB: "SUB", OP_SHR: "SHR", OP_SUBN: "SUBN", OP_SHL: "SHL",
}


# --- view 3: the plain Python golden reference ------------------------------------

def alu8_reference(vx: int, vy: int, op: int) -> Tuple[int, int]:
    """Return (result, vf) for one 8XY_ op, exactly as golden/chip8.py::_arith.

    vx, vy are 0..255, op is the low nibble. result is 0..255, vf is 0 or 1. VF for LD
    is defined as 0 here (see the module docstring). Unassigned ops return (0, 0).
    """
    vx &= 0xFF
    vy &= 0xFF
    if op == OP_LD:
        return vy, 0
    if op == OP_OR:
        return vx | vy, 0
    if op == OP_AND:
        return vx & vy, 0
    if op == OP_XOR:
        return vx ^ vy, 0
    if op == OP_ADD:
        total = vx + vy
        return total & 0xFF, (1 if total > 0xFF else 0)
    if op == OP_SUB:
        return (vx - vy) & 0xFF, (1 if vx >= vy else 0)
    if op == OP_SHR:
        return (vy >> 1) & 0xFF, vy & 0x1
    if op == OP_SUBN:
        return (vy - vx) & 0xFF, (1 if vy >= vx else 0)
    if op == OP_SHL:
        return (vy << 1) & 0xFF, (vy >> 7) & 0x1
    return 0, 0


# --- view 1: behavioural Amaranth reference ---------------------------------------

class Alu8(Elaboratable):
    """The CHIP-8 8XY_ ALU, behaviourally. Pure combinational function of (vx, vy, op).

    Inputs:  vx[8], vy[8], op[4].
    Outputs: result[8], vf.

    Matches alu8_reference exactly, including VF = 0 for LD and the vf_reset quirk
    (VF = 0) on OR/AND/XOR, and shift-uses-VY for SHR/SHL.
    """

    def __init__(self):
        self.vx = Signal(8)
        self.vy = Signal(8)
        self.op = Signal(4)
        self.result = Signal(8)
        self.vf = Signal()

    def elaborate(self, platform):
        m = Module()

        # ADD: 9-bit sum gives carry in bit 8.
        add = self.vx + self.vy                     # 9 bits
        # SUB: vx - vy; borrow when vx < vy, so VF = NOT borrow = (vx >= vy).
        sub = (self.vx - self.vy)                    # wraps mod 256 in the low 8
        # SUBN: vy - vx.
        subn = (self.vy - self.vx)

        with m.Switch(self.op):
            with m.Case(OP_LD):
                m.d.comb += self.result.eq(self.vy)
                m.d.comb += self.vf.eq(0)
            with m.Case(OP_OR):
                m.d.comb += self.result.eq(self.vx | self.vy)
                m.d.comb += self.vf.eq(0)
            with m.Case(OP_AND):
                m.d.comb += self.result.eq(self.vx & self.vy)
                m.d.comb += self.vf.eq(0)
            with m.Case(OP_XOR):
                m.d.comb += self.result.eq(self.vx ^ self.vy)
                m.d.comb += self.vf.eq(0)
            with m.Case(OP_ADD):
                m.d.comb += self.result.eq(add[:8])
                m.d.comb += self.vf.eq(add[8])
            with m.Case(OP_SUB):
                m.d.comb += self.result.eq(sub[:8])
                m.d.comb += self.vf.eq(self.vx >= self.vy)
            with m.Case(OP_SHR):
                m.d.comb += self.result.eq(self.vy >> 1)
                m.d.comb += self.vf.eq(self.vy[0])
            with m.Case(OP_SUBN):
                m.d.comb += self.result.eq(subn[:8])
                m.d.comb += self.vf.eq(self.vy >= self.vx)
            with m.Case(OP_SHL):
                m.d.comb += self.result.eq((self.vy << 1)[:8])
                m.d.comb += self.vf.eq(self.vy[7])
            with m.Default():
                m.d.comb += self.result.eq(0)
                m.d.comb += self.vf.eq(0)

        return m


# --- view 2: the structural gate-level netlist (the verified synth path) ----------

def build_alu8_netlist() -> Netlist:
    """Build the 8XY_ ALU as a gate-level Netlist using NetlistBuilder.

    Strategy: compute every op's 8-bit result and its VF bit as separate combinational
    cones, then select the active one with an 8-way one-hot mux driven by a 4-to-9 op
    decoder. The adder/subtractor cone reuses the ripple-carry full-adder pattern from
    hdl/adder.py, shared across ADD, SUB and SUBN by feeding it the right operands and
    carry-in (subtraction is x + ~y + 1).

    All emitters on NetlistBuilder lower to NOR under the hood, so the structural netlist
    is already buildable. to_nor() on the result performs a genuine re-lowering (walking
    the driver graph and re-expanding every gate), which the tests confirm stays equivalent
    and lands fully in {NOR, CONST0, CONST1}.
    """
    b = NetlistBuilder("alu8")

    vx = [b.declare_input(f"vx{i}") for i in range(8)]
    vy = [b.declare_input(f"vy{i}") for i in range(8)]
    op = [b.declare_input(f"op{i}") for i in range(4)]   # op0 = LSB

    # -- op decoder: one-hot select line per defined op ----------------------------
    # decode(value) is true iff op == value. op is 4 bits, so AND the matching literals.
    def decode(value: int) -> str:
        lits = []
        for i in range(4):
            bit = (value >> i) & 1
            lits.append(op[i] if bit else b.inv(op[i]))
        return b.and_(lits)

    sel = {code: decode(code) for code in DEFINED_OPS}

    # -- bitwise logic cones (cheap) ----------------------------------------------
    or_bits = [b.or_([vx[i], vy[i]]) for i in range(8)]
    and_bits = [b.and_([vx[i], vy[i]]) for i in range(8)]
    xor_bits = [b.xor2(vx[i], vy[i]) for i in range(8)]
    ld_bits = list(vy)                                   # LD: result = VY

    # -- shift cones --------------------------------------------------------------
    # SHR: result = VY >> 1, so result bit i = vy[i+1]; top bit 0; VF = vy[0].
    shr_bits = [vy[i + 1] if i < 7 else b.const0() for i in range(8)]
    shr_vf = vy[0]
    # SHL: result = (VY << 1) & 0xFF, so result bit i = vy[i-1]; bit 0 = 0; VF = vy[7].
    shl_bits = [b.const0() if i == 0 else vy[i - 1] for i in range(8)]
    shl_vf = vy[7]

    # -- adder / subtractor cone (shared ripple-carry, full-adder pattern) --------
    def ripple_add(xbits: List[str], ybits: List[str], cin: str):
        """8-bit ripple-carry add. Returns (sum_bits[8], carry_out)."""
        carry = cin
        sums = []
        for i in range(8):
            ai, bi = xbits[i], ybits[i]
            axb = b.xor2(ai, bi)              # a ^ b
            s_i = b.xor2(axb, carry)          # (a ^ b) ^ cin
            ab = b.and_([ai, bi])             # a & b
            cc = b.and_([carry, axb])         # cin & (a ^ b)
            carry = b.or_([ab, cc])           # next carry
            sums.append(s_i)
        return sums, carry

    not_vy = [b.inv(vy[i]) for i in range(8)]
    not_vx = [b.inv(vx[i]) for i in range(8)]

    # ADD: vx + vy + 0. VF = carry out.
    add_bits, add_carry = ripple_add(vx, vy, b.const0())
    add_vf = add_carry

    # SUB: vx - vy = vx + ~vy + 1. VF = carry out = NOT borrow = (vx >= vy).
    sub_bits, sub_carry = ripple_add(vx, not_vy, b.const1())
    sub_vf = sub_carry

    # SUBN: vy - vx = vy + ~vx + 1. VF = carry out = (vy >= vx).
    subn_bits, subn_carry = ripple_add(vy, not_vx, b.const1())
    subn_vf = subn_carry

    # -- per-op (result_bits, vf) table -------------------------------------------
    zero = b.const0()
    op_result: Dict[int, List[str]] = {
        OP_LD:   ld_bits,
        OP_OR:   or_bits,
        OP_AND:  and_bits,
        OP_XOR:  xor_bits,
        OP_ADD:  add_bits,
        OP_SUB:  sub_bits,
        OP_SHR:  shr_bits,
        OP_SUBN: subn_bits,
        OP_SHL:  shl_bits,
    }
    op_vf: Dict[int, str] = {
        OP_LD:   zero,
        OP_OR:   zero,
        OP_AND:  zero,
        OP_XOR:  zero,
        OP_ADD:  add_vf,
        OP_SUB:  sub_vf,
        OP_SHR:  shr_vf,
        OP_SUBN: subn_vf,
        OP_SHL:  shl_vf,
    }

    # -- one-hot mux: result bit j = OR over ops of (sel[op] AND op_result[op][j]) -
    # Exactly one sel line is high for any defined op, so the OR picks that op's bits.
    # For an undefined op every sel line is low and the result is all zero.
    for j in range(8):
        terms = [b.and_([sel[code], op_result[code][j]]) for code in DEFINED_OPS]
        rj = b.or_(terms)
        b.alias_output(f"r{j}", rj)

    vf_terms = [b.and_([sel[code], op_vf[code]]) for code in DEFINED_OPS]
    vf = b.or_(vf_terms)
    b.alias_output("vf", vf)

    return b.finish()
