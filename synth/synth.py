"""Synthesis entry point for the 4-bit adder.

synth_adder4() returns the lowered, buildable Netlist (NOR / CONST only). Running this
file as a script writes both the structural netlist and the lowered one to synth/out/:

    python synth/synth.py
      -> synth/out/adder4.json       (structural, readable gate types)
      -> synth/out/adder4_nor.json   (lowered to {NOR, CONST0, CONST1}, buildable)

The structural builder in hdl/adder.py is the verified synthesis path. A real yosys is
also reachable here (the WASM build bundled with amaranth-yosys) and is used as a cross
check in the tests, but that stripped build cannot techmap to a NOR cell library, so the
NOR lowering is done by Netlist.to_nor(). See synth/adder4.ys and STUCK notes for the
proper full-yosys path left for a human.
"""

from __future__ import annotations

import os
import sys

# allow "python synth/synth.py" from the repo root without conftest's sys.path help.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _d in (_HERE, os.path.join(_ROOT, "hdl")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from netlist import Netlist
from adder import build_adder4_netlist


def synth_structural() -> Netlist:
    """The structural gate-level adder (XOR/AND/OR emitted as NOR under the hood)."""
    return build_adder4_netlist()


def synth_adder4() -> Netlist:
    """Return the lowered, buildable adder netlist: only NOR / CONST0 / CONST1 cells."""
    return synth_structural().to_nor()


def _out_dir() -> str:
    d = os.path.join(_HERE, "out")
    os.makedirs(d, exist_ok=True)
    return d


def main() -> int:
    out = _out_dir()

    structural = synth_structural()
    lowered = structural.to_nor()

    struct_path = os.path.join(out, "adder4.json")
    nor_path = os.path.join(out, "adder4_nor.json")
    structural.save(struct_path)
    lowered.save(nor_path)

    s_stats = structural.stats()
    n_stats = lowered.stats()
    print("wrote", struct_path, f"({os.path.getsize(struct_path)} bytes)")
    print("wrote", nor_path, f"({os.path.getsize(nor_path)} bytes)")
    print("structural cells:", {k: v for k, v in s_stats.items() if not k.startswith("_")})
    print("lowered NOR gate count:", n_stats.get("NOR", 0))
    print("lowered total cells:", n_stats["_total_cells"], "nets:", n_stats["_nets"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
