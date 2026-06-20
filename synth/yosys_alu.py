"""Real-yosys synthesis of the CHIP-8 8-bit ALU to a buildable NOR netlist.

The ALU counterpart to synth/yosys_synth.py (which does the 4-bit adder). When a full yosys
(oss-cad-suite) is present, this emits the behavioural Amaranth Alu8 as verilog, runs the
real read_verilog -> synth -> abc -g NOR techmap, and imports the result. yosys's abc gives a
much tighter NOR cover than the structural Python flow (442 vs 891 cells), the same way the
adder went 92 -> 62. Skips cleanly when yosys is absent; the Python flow (hdl/alu.py +
Netlist.to_nor via synth/synth_alu.py) stays the tool-free verified default.

Equivalence at the ALU's 20 inputs cannot use the contract equivalent() (it enumerates 2^20
and hangs), so correctness is checked by sampled simulation of all nine ops against the golden
CHIP-8 interpreter, the same honest preservation check the structural ALU tests use.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
for _d in ("hdl", "golden"):
    sys.path.insert(0, os.path.join(REPO, _d))

from yosys_synth import find_yosys, run_yosys_nor, import_yosys_nor  # noqa: E402
from netlist import Netlist, BUILDABLE  # noqa: E402


def synth_alu8_yosys():
    """Emit ALU verilog, run the real yosys NOR techmap, import. None if yosys absent."""
    if find_yosys() is None:
        return None
    from amaranth.back import verilog
    from alu import Alu8
    d = Alu8()
    v = verilog.convert(d, ports=[d.vx, d.vy, d.op, d.result, d.vf], name="alu8")
    vpath = os.path.join(HERE, "alu8.v")
    open(vpath, "w").write(v)
    out = os.path.join(HERE, "out", "alu8_nor_yosys.json")
    run_yosys_nor(find_yosys(), vpath, out, top="alu8")
    return import_yosys_nor(out, top="alu8"), out


OPS = {0x0: "LD", 0x1: "OR", 0x2: "AND", 0x3: "XOR", 0x4: "ADD",
       0x5: "SUB", 0x6: "SHR", 0x7: "SUBN", 0xE: "SHL"}


def _golden(op, vx, vy):
    from chip8 import Chip8
    m = Chip8(seed=0)
    m.V[0] = vx
    m.V[1] = vy
    m.memory[0x200] = 0x80
    m.memory[0x201] = 0x10 | op
    m.pc = 0x200
    m.step()
    return m.V[0], m.V[0xF]


def alu_eval(nl: Netlist, op, vx, vy):
    iv = {}
    for i in range(8):
        iv[f"vx{i}"] = (vx >> i) & 1
        iv[f"vy{i}"] = (vy >> i) & 1
    for i in range(4):
        iv[f"op{i}"] = (op >> i) & 1
    o = nl.outputs_for(iv)
    return sum(o[f"result{i}"] << i for i in range(8)), o["vf"]


def errors(nl: Netlist) -> int:
    bad = 0
    for op in OPS:
        pairs = [(x, y) for x in range(0, 256, 15) for y in range(0, 256, 15)]
        pairs += [(0, 0), (255, 255), (255, 0), (0, 255), (170, 85), (1, 128)]
        for vx, vy in pairs:
            gr, gf = _golden(op, vx, vy)
            ar, af = alu_eval(nl, op, vx, vy)
            if op == 0x0:
                if ar != gr:
                    bad += 1
            elif ar != gr or af != gf:
                bad += 1
    return bad


if __name__ == "__main__":
    res = synth_alu8_yosys()
    if res is None:
        print("yosys not found; the Python ALU flow (synth/synth_alu.py) is the verified path.")
        sys.exit(0)
    nl, out = res
    print(f"real yosys -> {out}")
    print(f"  cells: {nl.stats().get('NOR', 0)} NOR  buildable-only:",
          set(c.type for c in nl.cells) <= BUILDABLE)
    print(f"  computes all 9 CHIP-8 ALU ops vs golden interpreter: "
          f"{'CORRECT' if errors(nl) == 0 else 'ERRORS'}")
