"""A tiny CHIP-8 assembler.

Just enough to hand-write the raycaster ROM (raycaster.py) without juggling raw
hex by hand. It is deliberately small: one pass to lay out instructions and
labels, a second pass to resolve label addresses, then emit big-endian bytes.

This is a real assembler, not a fake one. Every mnemonic maps to the exact
opcode the golden interpreter (chip8.py) decodes, so a program assembled here
executes for real on that interpreter. The opcode encodings are the standard
CHIP-8 set documented in Cowgod's reference and matched against chip8._execute.

Usage is programmatic, you build a list of instructions:

    a = Asm()
    a.label("start")
    a.LD_imm(0, 0x0A)        # 6X NN  -> V0 = 0x0A
    a.JP("start")            # 1NNN   -> jump to label
    a.db(0xDE, 0xAD)         # raw data bytes (tables)
    rom = a.assemble()       # -> bytes, base 0x200

Labels are resolved to absolute addresses (load base 0x200). `here()` gives the
current address so tables can be self-locating.
"""

from __future__ import annotations

PROGRAM_ADDR = 0x200


class Asm:
    def __init__(self, base: int = PROGRAM_ADDR):
        self.base = base
        # each item is either ("op", word) for a 2-byte instruction, an
        # ("raw", byte) for a data byte, or ("opref", fn) where fn(labels)->word
        # resolves a label into the final 12-bit address at assemble time.
        self.items: list = []
        self.labels: dict[str, int] = {}

    # --- layout helpers -----------------------------------------------------

    def here(self) -> int:
        """Address of the next item to be emitted. Each op/opref item is two
        bytes, each raw item is one byte, so the address is the running byte
        total, not the item count."""
        n = 0
        for item in self.items:
            n += 1 if item[0] == "raw" else 2
        return self.base + n

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate label {name!r}")
        self.labels[name] = self.here()

    def align2(self) -> None:
        """Pad with a zero byte so the next item starts on an even address.
        Instructions must be 2-byte aligned; after an odd run of data bytes
        this restores alignment."""
        if (self.here() - self.base) % 2 != 0:
            self.items.append(("raw", 0x00))

    # --- raw data -----------------------------------------------------------

    def db(self, *bytes_: int) -> None:
        for b in bytes_:
            self.items.append(("raw", b & 0xFF))

    # --- instruction emitters ----------------------------------------------
    # names mirror common CHIP-8 assembler mnemonics. each appends one 2-byte
    # word (or a deferred resolver for label operands).

    def _emit(self, word: int) -> None:
        self.items.append(("op", word & 0xFFFF))

    def _emit_ref(self, high_nibble: int, label: str, reg: int | None = None) -> None:
        # deferred: encode high nibble (and optional X reg) with a 12-bit addr.
        def resolve(labels):
            addr = labels[label] & 0x0FFF
            if reg is None:
                return (high_nibble << 12) | addr
            return (high_nibble << 12) | (reg << 8) | addr
        self.items.append(("opref", resolve))

    # 00E0 / 00EE
    def CLS(self):      self._emit(0x00E0)
    def RET(self):      self._emit(0x00EE)

    # 1NNN jump, 2NNN call, BNNN jump+V0
    def JP(self, label):    self._emit_ref(0x1, label)
    def CALL(self, label):  self._emit_ref(0x2, label)
    def JP_V0(self, label): self._emit_ref(0xB, label)

    # 3XNN / 4XNN skip eq/neq imm, 5XY0 / 9XY0 skip eq/neq reg
    def SE_imm(self, x, nn):  self._emit(0x3000 | (x << 8) | (nn & 0xFF))
    def SNE_imm(self, x, nn): self._emit(0x4000 | (x << 8) | (nn & 0xFF))
    def SE_reg(self, x, y):   self._emit(0x5000 | (x << 8) | (y << 4))
    def SNE_reg(self, x, y):  self._emit(0x9000 | (x << 8) | (y << 4))

    # 6XNN set, 7XNN add imm
    def LD_imm(self, x, nn):  self._emit(0x6000 | (x << 8) | (nn & 0xFF))
    def ADD_imm(self, x, nn): self._emit(0x7000 | (x << 8) | (nn & 0xFF))

    # 8XY_ ALU
    def LD(self, x, y):   self._emit(0x8000 | (x << 8) | (y << 4))
    def OR(self, x, y):   self._emit(0x8001 | (x << 8) | (y << 4))
    def AND(self, x, y):  self._emit(0x8002 | (x << 8) | (y << 4))
    def XOR(self, x, y):  self._emit(0x8003 | (x << 8) | (y << 4))
    def ADD(self, x, y):  self._emit(0x8004 | (x << 8) | (y << 4))
    def SUB(self, x, y):  self._emit(0x8005 | (x << 8) | (y << 4))
    def SHR(self, x, y):  self._emit(0x8006 | (x << 8) | (y << 4))
    def SUBN(self, x, y): self._emit(0x8007 | (x << 8) | (y << 4))
    def SHL(self, x, y):  self._emit(0x800E | (x << 8) | (y << 4))

    # ANNN set I (immediate or label)
    def LD_I(self, nnn):       self._emit(0xA000 | (nnn & 0x0FFF))
    def LD_I_label(self, label): self._emit_ref(0xA, label)

    # CXNN random
    def RND(self, x, nn): self._emit(0xC000 | (x << 8) | (nn & 0xFF))

    # DXYN draw
    def DRW(self, x, y, n): self._emit(0xD000 | (x << 8) | (y << 4) | (n & 0xF))

    # EX9E / EXA1 keys
    def SKP(self, x):  self._emit(0xE09E | (x << 8))
    def SKNP(self, x): self._emit(0xE0A1 | (x << 8))

    # FX__ misc
    def LD_VX_DT(self, x): self._emit(0xF007 | (x << 8))
    def LD_VX_K(self, x):  self._emit(0xF00A | (x << 8))
    def LD_DT_VX(self, x): self._emit(0xF015 | (x << 8))
    def LD_ST_VX(self, x): self._emit(0xF018 | (x << 8))
    def ADD_I(self, x):    self._emit(0xF01E | (x << 8))
    def LD_F(self, x):     self._emit(0xF029 | (x << 8))
    def LD_B(self, x):     self._emit(0xF033 | (x << 8))
    def STORE(self, x):    self._emit(0xF055 | (x << 8))  # FX55 V0..VX -> [I]
    def LOAD(self, x):     self._emit(0xF065 | (x << 8))  # FX65 [I] -> V0..VX

    # --- assembly -----------------------------------------------------------

    def assemble(self) -> bytes:
        out = bytearray()
        for item in self.items:
            kind = item[0]
            if kind == "raw":
                out.append(item[1])
            elif kind == "op":
                w = item[1]
                out.append((w >> 8) & 0xFF)
                out.append(w & 0xFF)
            elif kind == "opref":
                w = item[1](self.labels)
                out.append((w >> 8) & 0xFF)
                out.append(w & 0xFF)
            else:  # pragma: no cover - internal invariant.
                raise AssertionError(kind)
        return bytes(out)
