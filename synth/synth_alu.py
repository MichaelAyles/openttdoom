"""Synthesis entry point for the CHIP-8 8XY_ ALU (Track B).

Mirrors synth/synth.py, which handles the 4-bit adder. Kept as a separate module so the
existing, verified adder path in synth.py is untouched.

synth_alu8() returns the lowered, buildable Netlist (NOR / CONST only). Running this file
as a script writes both the structural netlist and the lowered one to synth/out/:

    python synth/synth_alu.py
      -> synth/out/alu8.json       (structural, NOR-heavy: the builder emits NOR directly)
      -> synth/out/alu8_nor.json   (re-lowered to {NOR, CONST0, CONST1}, buildable)

The structural builder in hdl/alu.py is the verified synthesis path and needs no external
tools. The NOR lowering is done by Netlist.to_nor(). There is no yosys cross-check here: the
ALU's 20 primary inputs make a full 2^20 truth-table equivalence infeasible, so equivalence
is checked by sampled simulation in hdl/test_alu.py instead (see the note there).
"""

from __future__ import annotations

import os
import sys

# allow "python synth/synth_alu.py" from the repo root without conftest's sys.path help.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _d in (_HERE, os.path.join(_ROOT, "hdl")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from netlist import Netlist
from alu import build_alu8_netlist


def synth_structural() -> Netlist:
    """The structural gate-level ALU (gate emitters emit NOR under the hood)."""
    return build_alu8_netlist()


def synth_alu8() -> Netlist:
    """Return the lowered, buildable ALU netlist: only NOR / CONST0 / CONST1 cells."""
    return synth_structural().to_nor()


def _out_dir() -> str:
    d = os.path.join(_HERE, "out")
    os.makedirs(d, exist_ok=True)
    return d


def main() -> int:
    out = _out_dir()

    structural = synth_structural()
    lowered = structural.to_nor()

    struct_path = os.path.join(out, "alu8.json")
    nor_path = os.path.join(out, "alu8_nor.json")
    structural.save(struct_path)
    lowered.save(nor_path)

    s_stats = structural.stats()
    n_stats = lowered.stats()
    print("wrote", struct_path, f"({os.path.getsize(struct_path)} bytes)")
    print("wrote", nor_path, f"({os.path.getsize(nor_path)} bytes)")
    print("structural cells:", {k: v for k, v in s_stats.items() if not k.startswith("_")})
    print("structural total cells:", s_stats["_total_cells"], "nets:", s_stats["_nets"])
    print("lowered NOR gate count:", n_stats.get("NOR", 0))
    print("lowered total cells:", n_stats["_total_cells"], "nets:", n_stats["_nets"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
