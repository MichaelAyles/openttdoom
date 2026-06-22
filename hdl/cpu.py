"""A minimal 8-bit accumulator CPU, end to end, the sequential capstone of the toolchain.

hdl/adder.py and hdl/alu.py are pure combinational. hdl/sequential.py added the clocked
m.d.sync -> register + NOR path on tiny worked examples (a toggle, a counter). This module is
the real clocked design those pieces were built for: a whole little CPU that FETCHES and
EXECUTES a hardwired program and emits the Fibonacci sequence on a memory-mapped output latch.

It is deliberately the LEAN accumulator machine the spec asks for, NOT a CHIP-8 and NOT a
wrapper around the 891-NOR ALU. State is the scarce resource (every bit is a register tile on
the train substrate), so the machine keeps only:

    ACC   8 bits   the accumulator (the one working register)
    PC    4 bits   the program counter (a 16-word program ROM)
    Z     1 bit    the zero flag, set from the last ALU/load result
    phase 1 bit    a two-state FETCH / EXEC control FSM
    DMEM  a tiny writable data memory (DMEM_WORDS bytes: the two Fibonacci terms, a scratch
          temporary, and the memory-mapped OUTPUT latch address)

So the whole architectural state is ACC(8) + PC(4) + Z(1) + phase(1) + DMEM(DMEM_WORDS*8). That
is the honest register budget the report counts.

ISA (six opcodes, an 8-bit instruction word = opcode in the high nibble, 4-bit operand in the
low nibble):

    LDI imm    ACC <- imm                 (load a small immediate 0..15); Z from result
    ADD addr   ACC <- ACC + DMEM[addr]     8-bit add; Z from the 8-bit result
    SUB addr   ACC <- ACC - DMEM[addr]     8-bit sub via x + ~y + 1; Z from the 8-bit result
    STA addr   DMEM[addr] <- ACC           (writes a scratch reg, or the OUTPUT latch)
    BZ  addr   if Z: PC <- addr            (branch if the zero flag is set)
    JMP addr   PC <- addr                  (unconditional jump)

Only ADD/SUB/pass(LDI/STA leave the adder unused) are needed, so the datapath reuses the
ripple-carry full adder and the sub = x + ~y + 1 trick from hdl/adder.py / hdl/alu.py, NOT the
whole ALU. The zero flag is a wide-NOR of the 8-bit result. The write-back into ACC is a small
result mux (immediate vs ALU result vs unchanged).

Timing model. A two-phase machine, one clock edge per phase:
  FETCH: read the instruction at ROM[PC] (combinational, ROM is hardwired), latch its decoded
         fields, and advance PC to PC+1; then go to EXEC.
  EXEC:  carry out the latched instruction (update ACC/DMEM/Z, and a taken branch/jump
         overwrites PC); then go back to FETCH.
The memory-mapped OUTPUT latch (DMEM[OUT_ADDR]) is what an external observer reads; the
Fibonacci program STA's each term to it in turn.

Three views, mirroring hdl/adder.py and hdl/alu.py:

  1. Cpu: a behavioural Amaranth module (m.d.sync registers for ACC/PC/Z/phase/DMEM), the
     golden hardware, simulated with amaranth.sim. The output stream it emits is asserted to be
     exactly the 13 Fibonacci terms, then the mod-256 overflow term, in the tests.
  2. cpu_reference(): a plain Python interpreter of the same ISA over the same ROM, the ground
     truth both other views are checked against (mirrors alu8_reference / counter_reference).
  3. build_cpu_netlist(): a STRUCTURAL gate + DFF Netlist of the whole datapath built from
     NetlistBuilder + b.dff_into() feedback registers, lowering cleanly to {NOR, CONST0,
     CONST1} + the register tiles via .to_nor(keep_registers=True). It steps cycle-for-cycle
     identically to the behavioural module under SeqSim, so the whole CPU flows through the
     real sequential place-and-route the same way the toggle/counter did.

The FIBONACCI program (FIB_PROGRAM below) emits 1,1,2,3,5,8,13,21,34,55,89,144,233 (the 13
terms that fit in 8 bits) on the output latch, then keeps running: the 14th term 377 overflows
8 bits to 377 & 0xFF = 121, and the machine free-runs the Fibonacci recurrence MODULO 256 from
there. The tests pin the exact 13-term stream and the 121 overflow term. The loop uses no
temporary: after computing next = A + B it slides the window with the identity oldB =
next - oldA (because next = oldA + oldB), so SUB does the slide and the body fits the 16-word ROM
with a JMP.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from amaranth.hdl import Array, Cat, Const, Elaboratable, Module, Signal

from netlist import Netlist, NetlistBuilder


# --- ISA definition ----------------------------------------------------------------

# opcodes live in the high nibble of the 8-bit instruction word.
OP_LDI = 0x0   # ACC <- imm
OP_ADD = 0x1   # ACC <- ACC + DMEM[addr]
OP_SUB = 0x2   # ACC <- ACC - DMEM[addr]
OP_STA = 0x3   # DMEM[addr] <- ACC
OP_BZ = 0x4    # if Z: PC <- addr
OP_JMP = 0x5   # PC <- addr

OPCODES = (OP_LDI, OP_ADD, OP_SUB, OP_STA, OP_BZ, OP_JMP)
OP_NAME = {
    OP_LDI: "LDI", OP_ADD: "ADD", OP_SUB: "SUB",
    OP_STA: "STA", OP_BZ: "BZ", OP_JMP: "JMP",
}

# data-memory geometry. A handful of scratch bytes is all Fibonacci needs.
DMEM_WORDS = 4        # addresses 0..3
A_ADDR = 0            # Fibonacci term n-1 (the running low term)
B_ADDR = 1            # Fibonacci term n   (the running high term)
OUT_ADDR = 2          # the memory-mapped OUTPUT latch (what an observer reads)
T_ADDR = 3            # a scratch temporary (unused by Fibonacci, used by ISA tests)

PROG_WORDS = 16       # a 16-word ROM, PC is 4 bits
PC_BITS = 4
ACC_BITS = 8


def encode(op: int, operand: int) -> int:
    """Pack an opcode (high nibble) and a 4-bit operand (low nibble) into an 8-bit word."""
    return ((op & 0xF) << 4) | (operand & 0xF)


def decode_word(word: int) -> Tuple[int, int]:
    """Split an 8-bit instruction word into (opcode, operand)."""
    return (word >> 4) & 0xF, word & 0xF


def disassemble(prog: List[int]) -> List[str]:
    """Human-readable listing of a program ROM, for debugging and the tests' messages."""
    out = []
    for i, w in enumerate(prog):
        op, operand = decode_word(w)
        name = OP_NAME.get(op, f"OP{op:X}")
        out.append(f"{i:2d}: {name} {operand}")
    return out


# --- the Fibonacci program ---------------------------------------------------------
#
# A = prev term, B = current term. ACC is the working register. The window slide
# (A, B) -> (B, A+B) is done with NO temporary using the identity oldB = next - oldA, since
# next = oldA + oldB. So after computing next = A + B and emitting it, we set B <- next, then
# SUB A (ACC = next - oldA = oldB, A still holds oldA because we have not written it yet), then
# A <- oldB. That keeps the loop body short enough to fit a JMP in the 16-word ROM.

def _fib_rom() -> List[int]:
    A, B, OUT = A_ADDR, B_ADDR, OUT_ADDR
    return [
        encode(OP_LDI, 1),     # 0  ACC = 1
        encode(OP_STA, A),     # 1  A = 1                         (term n-1)
        encode(OP_STA, OUT),   # 2  emit 1                        -> term 1
        encode(OP_STA, B),     # 3  B = 1                         (term n)
        encode(OP_STA, OUT),   # 4  emit 1                        -> term 2
        encode(OP_LDI, 0),     # 5  LOOP: ACC = 0
        encode(OP_ADD, A),     # 6  ACC = A
        encode(OP_ADD, B),     # 7  ACC = A + B = next
        encode(OP_STA, OUT),   # 8  emit next                     -> terms 3..
        encode(OP_STA, B),     # 9  B = next
        encode(OP_SUB, A),     # 10 ACC = next - oldA = oldB
        encode(OP_STA, A),     # 11 A = oldB                      (slide complete)
        encode(OP_JMP, 5),     # 12 jump back to LOOP
        encode(OP_LDI, 0),     # 13 (unreached pad)
        encode(OP_LDI, 0),     # 14 (unreached pad)
        encode(OP_LDI, 0),     # 15 (unreached pad)
    ]


FIB_PROGRAM: List[int] = _fib_rom()

# The 13 Fibonacci terms that fit in an 8-bit byte, then the first mod-256 overflow term.
FIB_TERMS_8BIT = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233]
FIB_OVERFLOW_TERM = (233 + 144) & 0xFF      # 377 & 0xFF = 121


# --- view 3: the plain Python golden reference -------------------------------------

def cpu_reference(
    program: List[int],
    steps: int,
    capture_addr: int = OUT_ADDR,
    dmem_words: int = DMEM_WORDS,
) -> Dict[str, object]:
    """Interpret the accumulator ISA over `program` for `steps` instruction executions.

    Returns a dict with the final architectural state and the OUTPUT STREAM: every value
    written to DMEM[capture_addr] by a STA, in order. This single-instruction-per-step model is
    the ARCHITECTURAL ground truth (one step == one full FETCH+EXEC of one instruction); the
    two-phase Amaranth/netlist machine takes two clock edges per instruction but realises the
    same per-instruction semantics, which the tests check by comparing output streams.

    The ISA, exactly:
      LDI imm  : ACC <- imm & 0xFF              ; Z <- (ACC == 0)
      ADD addr : ACC <- (ACC + DMEM[addr])&0xFF ; Z <- (ACC == 0)
      SUB addr : ACC <- (ACC - DMEM[addr])&0xFF ; Z <- (ACC == 0)
      STA addr : DMEM[addr] <- ACC              ; (no flag change); emits if addr==capture_addr
      BZ  addr : if Z: PC <- addr
      JMP addr : PC <- addr
    PC is PC_BITS wide and wraps; falling off the end wraps to 0.
    """
    acc = 0
    pc = 0
    z = 0
    dmem = [0] * dmem_words
    out_stream: List[int] = []
    pc_mask = (1 << PC_BITS) - 1

    def read(addr: int) -> int:
        # Exact one-hot decode, matching the structural netlist: an address outside DMEM reads 0
        # (no word matches the decode), it does NOT wrap. The assembler only uses 0..dmem_words-1.
        return dmem[addr] if 0 <= addr < dmem_words else 0

    for _ in range(steps):
        word = program[pc & pc_mask]
        op, operand = decode_word(word)
        pc = (pc + 1) & pc_mask                 # advance (FETCH increments PC)
        if op == OP_LDI:
            acc = operand & 0xFF
            z = 1 if acc == 0 else 0
        elif op == OP_ADD:
            acc = (acc + read(operand)) & 0xFF
            z = 1 if acc == 0 else 0
        elif op == OP_SUB:
            acc = (acc - read(operand)) & 0xFF
            z = 1 if acc == 0 else 0
        elif op == OP_STA:
            if 0 <= operand < dmem_words:       # an out-of-range STA writes nowhere (no decode)
                dmem[operand] = acc
                if operand == capture_addr:
                    out_stream.append(acc)
        elif op == OP_BZ:
            if z:
                pc = operand & pc_mask
        elif op == OP_JMP:
            pc = operand & pc_mask
        # unknown opcodes are NOPs (defensive; the assembler only emits the six above).

    return {"acc": acc, "pc": pc, "z": z, "dmem": dmem, "out_stream": out_stream}


def fibonacci_reference(steps: int) -> List[int]:
    """Convenience: the OUTPUT STREAM of FIB_PROGRAM run for `steps` instructions."""
    return cpu_reference(FIB_PROGRAM, steps)["out_stream"]  # type: ignore[return-value]


# --- view 1: behavioural Amaranth (m.d.sync) ---------------------------------------

# phase encoding for the two-state control FSM.
PH_FETCH = 0
PH_EXEC = 1


class Cpu(Elaboratable):
    """The accumulator CPU, behaviourally, with m.d.sync registers for all architectural state.

    Ports:
      out_port  [8]  the value being EMITTED on the current cycle. A STA to the OUTPUT latch
                     writes ACC into DMEM[OUT_ADDR] on the next edge, so the value emitted at
                     the strobe IS the current ACC; out_port therefore tracks ACC and is read
                     by the testbench exactly on the cycle out_we pulses (the committed value,
                     with no one-cycle write-latency skew against the latch register).
      out_we         pulses high for one cycle (the EXEC cycle of a STA-to-OUT) when a value is
                     emitted, so a testbench can sample exactly the emitted stream, in order,
                     with no same-value de-duplication ambiguity.
      acc       [8]  ACC, exposed for debugging / the structural cross-check.
      pc        [PC_BITS]  PC, exposed for debugging.
      z              the zero flag, exposed for debugging.

    The program ROM is hardwired (a constant Array). DMEM is a small register file. The machine
    runs forever; a testbench clocks it and records out_port whenever out_we pulses.
    """

    def __init__(self, program: List[int] | None = None, dmem_words: int = DMEM_WORDS):
        self.program = list(program if program is not None else FIB_PROGRAM)
        if len(self.program) != PROG_WORDS:
            raise ValueError(f"program must be {PROG_WORDS} words, got {len(self.program)}")
        self.dmem_words = dmem_words
        self.out_port = Signal(8)
        self.out_we = Signal()
        self.acc = Signal(8)
        self.pc = Signal(PC_BITS)
        self.z = Signal()

    def elaborate(self, platform):
        m = Module()

        # architectural state registers (m.d.sync, so amaranth infers flip-flops). Every
        # register powers on at 0 (the sync-domain reset, PH_FETCH == 0), which is the default
        # init, so it is left implicit.
        acc = Signal(8)
        pc = Signal(PC_BITS)
        z = Signal()
        phase = Signal(init=PH_FETCH)
        dmem = Array(Signal(8, name=f"dmem{i}") for i in range(self.dmem_words))

        # latched decode of the instruction fetched this FETCH phase, used in EXEC.
        ir_op = Signal(4)
        ir_arg = Signal(4)

        # hardwired program ROM (constant lookup).
        rom = Array(Const(w, 8) for w in self.program)

        m.d.comb += [
            # out_port carries the value being emitted (ACC, the value a STA writes), so it is
            # read on the same cycle out_we strobes, free of the latch's one-edge write latency.
            self.out_port.eq(acc),
            self.acc.eq(acc),
            self.pc.eq(pc),
            self.z.eq(z),
        ]
        m.d.comb += self.out_we.eq(0)           # default; pulsed in EXEC on a STA to OUT

        # current instruction word at PC (combinational ROM read).
        word = Signal(8)
        m.d.comb += word.eq(rom[pc])

        with m.Switch(phase):
            with m.Case(PH_FETCH):
                # latch the decoded instruction, advance PC, move to EXEC.
                m.d.sync += [
                    ir_op.eq(word[4:8]),
                    ir_arg.eq(word[0:4]),
                    pc.eq(pc + 1),
                    phase.eq(PH_EXEC),
                ]
            with m.Case(PH_EXEC):
                # the ALU: ADD computes acc + dmem[arg], SUB computes acc - dmem[arg].
                operand = dmem[ir_arg]
                add_res = (acc + operand)[:8]
                sub_res = (acc - operand)[:8]
                with m.Switch(ir_op):
                    with m.Case(OP_LDI):
                        m.d.sync += acc.eq(ir_arg)
                        m.d.sync += z.eq(ir_arg == 0)
                    with m.Case(OP_ADD):
                        m.d.sync += acc.eq(add_res)
                        m.d.sync += z.eq(add_res == 0)
                    with m.Case(OP_SUB):
                        m.d.sync += acc.eq(sub_res)
                        m.d.sync += z.eq(sub_res == 0)
                    with m.Case(OP_STA):
                        m.d.sync += dmem[ir_arg].eq(acc)
                        with m.If(ir_arg == OUT_ADDR):
                            m.d.comb += self.out_we.eq(1)
                    with m.Case(OP_BZ):
                        with m.If(z):
                            m.d.sync += pc.eq(ir_arg)
                    with m.Case(OP_JMP):
                        m.d.sync += pc.eq(ir_arg)
                m.d.sync += phase.eq(PH_FETCH)

        return m


# --- view 2: the structural gate + DFF netlist (the verified synth path) -----------

def build_cpu_netlist(program: List[int] | None = None,
                      dmem_words: int = DMEM_WORDS) -> Netlist:
    """Build the whole accumulator CPU as a gate-level + DFF Netlist using NetlistBuilder.

    Every architectural bit is a DFF (a register tile): ACC[8], PC[PC_BITS], Z, phase, and
    DMEM[dmem_words][8]. The instruction-latch bits (IR op[4], arg[4]) are registers too, since
    the EXEC phase consumes the instruction the FETCH phase latched. All next-state and output
    logic is combinational gates (the ADD/SUB ripple adder, the one-hot opcode decode, the
    result mux, the zero wide-NOR, the ROM as a hardwired multiplexer), built from the same
    NetlistBuilder emitters as hdl/alu.py and hdl/adder.py, so the whole thing lowers to
    {NOR, CONST0, CONST1} + the register tiles via to_nor(keep_registers=True).

    Ports:
      inputs : clk
      outputs: out0..out7  (the OUTPUT latch, DMEM[OUT_ADDR]), out_we (STA-to-OUT strobe),
               acc0..acc7, pc0..pc{PC_BITS-1}, z, phase   (state, exposed for the cross-check)

    The structure mirrors the behavioural Cpu exactly (same two-phase FSM, same ISA), and the
    tests step both with SeqSim over the same clock schedule and assert identical output streams,
    which is the sequential_equivalent contract from synth/netlist.py applied to a real CPU.
    """
    program = list(program if program is not None else FIB_PROGRAM)
    if len(program) != PROG_WORDS:
        raise ValueError(f"program must be {PROG_WORDS} words, got {len(program)}")

    b = NetlistBuilder("cpu")
    clk = b.declare_input("clk")
    zero = b.const0()
    one = b.const1()

    # -- helpers over multi-bit buses (lists of net names, bit 0 = LSB) --------------

    def reg(width: int):
        """Reserve `width` register Q nets up front (so next-state logic can read them)."""
        return [b.fresh_net() for _ in range(width)]

    def const_bits(value: int, width: int) -> List[str]:
        return [one if (value >> i) & 1 else zero for i in range(width)]

    def mux2_bit(sel: str, a: str, b_: str) -> str:
        """1-bit 2:1 mux: sel ? b_ : a  ==  (a AND NOT sel) OR (b_ AND sel)."""
        nsel = b.inv(sel)
        return b.or_([b.and_([a, nsel]), b.and_([b_, sel])])

    def mux2(sel: str, a: List[str], b_: List[str]) -> List[str]:
        return [mux2_bit(sel, a[i], b_[i]) for i in range(len(a))]

    def ripple_add(xb: List[str], yb: List[str], cin: str):
        """n-bit ripple-carry add. Returns (sum_bits, carry_out)."""
        carry = cin
        sums = []
        for i in range(len(xb)):
            axb = b.xor2(xb[i], yb[i])
            s_i = b.xor2(axb, carry)
            ab = b.and_([xb[i], yb[i]])
            cc = b.and_([carry, axb])
            carry = b.or_([ab, cc])
            sums.append(s_i)
        return sums, carry

    def eq_const(bus: List[str], value: int) -> str:
        """1 iff the bus equals the constant `value` (AND of matched literals)."""
        lits = []
        for i in range(len(bus)):
            lits.append(bus[i] if (value >> i) & 1 else b.inv(bus[i]))
        return b.and_(lits)

    def is_zero(bus: List[str]) -> str:
        """Wide-NOR zero detect: 1 iff every bit is 0."""
        return b.nor(list(bus))

    def decode_addr(arg: List[str]):
        """One-hot decode of the 4-bit operand to the dmem_words addresses (low bits used)."""
        return [eq_const(arg, a) for a in range(dmem_words)]

    # -- architectural state: reserve every register's Q net -------------------------
    acc = reg(8)
    pc = reg(PC_BITS)
    z = reg(1)
    phase = reg(1)
    ir_op = reg(4)
    ir_arg = reg(4)
    dmem = [reg(8) for _ in range(dmem_words)]

    in_fetch = b.inv(phase[0])      # phase == PH_FETCH (0)
    in_exec = phase[0]              # phase == PH_EXEC  (1)

    # -- hardwired ROM: word = ROM[pc], a 256-way... no, 16-way 8-bit mux on pc -------
    # Build each of the 8 output bits as an OR over the 16 program words of
    # (pc == addr) AND romword_bit. pc is PC_BITS wide.
    pc_onehot = [eq_const(pc, addr) for addr in range(PROG_WORDS)]
    word = []
    for bit in range(8):
        terms = []
        for addr in range(PROG_WORDS):
            if (program[addr] >> bit) & 1:
                terms.append(pc_onehot[addr])
        word.append(b.or_(terms) if terms else zero)
    word_op = word[4:8]
    word_arg = word[0:4]

    # -- operand = DMEM[ir_arg], an addressed read of the data memory ----------------
    arg_onehot = decode_addr(ir_arg)
    operand = []
    for bit in range(8):
        terms = [b.and_([arg_onehot[a], dmem[a][bit]]) for a in range(dmem_words)]
        operand.append(b.or_(terms))

    # -- the ALU: ADD = acc + operand, SUB = acc + ~operand + 1 ----------------------
    not_operand = [b.inv(operand[i]) for i in range(8)]
    add_bits, _add_c = ripple_add(acc, operand, zero)
    sub_bits, _sub_c = ripple_add(acc, not_operand, one)

    # one-hot opcode decode of the LATCHED ir_op (used in EXEC).
    op_is = {code: eq_const(ir_op, code) for code in OPCODES}

    # -- ACC next-state ---------------------------------------------------------------
    # In EXEC: LDI -> ir_arg (zero-extended), ADD -> add_bits, SUB -> sub_bits, else hold.
    ir_arg_ext = list(ir_arg) + [zero, zero, zero, zero]    # 4-bit imm -> 8 bits
    acc_exec = list(acc)                                    # default hold
    acc_exec = mux2(op_is[OP_LDI], acc_exec, ir_arg_ext)
    acc_exec = mux2(op_is[OP_ADD], acc_exec, add_bits)
    acc_exec = mux2(op_is[OP_SUB], acc_exec, sub_bits)
    # ACC only changes in EXEC; in FETCH it holds.
    acc_next = mux2(in_exec, list(acc), acc_exec)
    for i in range(8):
        b.dff_into(acc_next[i], clk, acc[i])

    # -- Z next-state -----------------------------------------------------------------
    # Z updates in EXEC for LDI/ADD/SUB to (result == 0), else holds.
    ldi_zero = is_zero(ir_arg_ext)
    add_zero = is_zero(add_bits)
    sub_zero = is_zero(sub_bits)
    z_exec = z[0]                                           # default hold
    z_exec = mux2_bit(op_is[OP_LDI], z_exec, ldi_zero)
    z_exec = mux2_bit(op_is[OP_ADD], z_exec, add_zero)
    z_exec = mux2_bit(op_is[OP_SUB], z_exec, sub_zero)
    z_next = mux2_bit(in_exec, z[0], z_exec)
    b.dff_into(z_next, clk, z[0])

    # -- DMEM next-state: each word updates on STA addr==a in EXEC -------------------
    for a in range(dmem_words):
        # write enable for word a: EXEC and op==STA and ir_arg decodes to a.
        we = b.and_([in_exec, op_is[OP_STA], arg_onehot[a]])
        for bit in range(8):
            new_bit = mux2_bit(we, dmem[a][bit], acc[bit])
            b.dff_into(new_bit, clk, dmem[a][bit])

    # -- PC next-state ----------------------------------------------------------------
    # FETCH: pc <- pc + 1. EXEC: pc <- ir_arg on JMP, or on (BZ and z), else hold.
    pc_plus1, _c = ripple_add(pc, const_bits(1, PC_BITS), zero)
    take_branch = b.or_([op_is[OP_JMP], b.and_([op_is[OP_BZ], z[0]])])
    pc_exec = mux2(take_branch, list(pc), list(ir_arg))    # ir_arg is PC_BITS=4 wide
    # in FETCH use pc+1, in EXEC use pc_exec.
    pc_next = mux2(in_fetch, pc_exec, pc_plus1)
    for i in range(PC_BITS):
        b.dff_into(pc_next[i], clk, pc[i])

    # -- IR latch next-state: in FETCH latch the fetched word's fields, else hold ----
    for i in range(4):
        op_next = mux2_bit(in_fetch, ir_op[i], word_op[i])
        b.dff_into(op_next, clk, ir_op[i])
        arg_next = mux2_bit(in_fetch, ir_arg[i], word_arg[i])
        b.dff_into(arg_next, clk, ir_arg[i])

    # -- phase next-state: toggle each cycle (FETCH<->EXEC) --------------------------
    b.dff_into(b.inv(phase[0]), clk, phase[0])

    # -- outputs ----------------------------------------------------------------------
    # out{bit} carries the value being EMITTED (ACC, the value a STA-to-OUT writes), read on
    # the same cycle out_we strobes, matching the behavioural Cpu's out_port. The actual OUTPUT
    # latch register is DMEM[OUT_ADDR]; it holds this value from the NEXT edge, so reading ACC at
    # the strobe avoids the one-edge write latency. (DMEM[OUT_ADDR] is still a real register and
    # is checked by the cone reconstruction; it is just not the port read for the stream.)
    for bit in range(8):
        b.alias_output(f"out{bit}", acc[bit])
    # out_we: pulses in EXEC when op==STA and ir_arg==OUT_ADDR (a write to the OUT latch).
    out_we = b.and_([in_exec, op_is[OP_STA], arg_onehot[OUT_ADDR]])
    b.alias_output("out_we", out_we)
    for i in range(8):
        b.alias_output(f"acc{i}", acc[i])
    for i in range(PC_BITS):
        b.alias_output(f"pc{i}", pc[i])
    b.alias_output("z", z[0])
    b.alias_output("phase", phase[0])

    return b.finish()


# --- structural-netlist stream extraction ------------------------------------------

def netlist_output_stream(netlist: Netlist, instructions: int,
                          clock: str = "clk") -> List[int]:
    """Step `netlist` (a built CPU) for `instructions` instructions under SeqSim and return the
    emitted output stream (the values strobed onto the OUT latch by out_we).

    The two-phase machine takes TWO clock cycles per instruction, so we clock 2*instructions
    edges and sample on the cycle where out_we is high. out_we is a clean one-cycle strobe per
    STA-to-OUT, so the stream is captured with no same-value de-duplication ambiguity.
    """
    from netlist import SeqSim

    sim = SeqSim(netlist)
    sim.reset({clock: 0})
    stream: List[int] = []
    for _ in range(2 * instructions):
        sim.clock_cycle({}, clock=clock)
        if sim.value("out_we") == 1:
            val = sum(sim.value(f"out{bit}") << bit for bit in range(8))
            stream.append(val)
    return stream


def netlist_stats(netlist: Netlist) -> Dict[str, int]:
    """Cell-type counts plus register-bit and lowered-NOR totals, for the report."""
    s = dict(netlist.stats())
    low = netlist.to_nor(keep_registers=True)
    ls = low.stats()
    s["_lowered_NOR"] = ls.get("NOR", 0)
    s["_lowered_DFF"] = ls.get("DFF", 0)
    s["_lowered_CONST0"] = ls.get("CONST0", 0)
    s["_lowered_CONST1"] = ls.get("CONST1", 0)
    s["_lowered_total"] = ls.get("_total_cells", 0)
    return s
