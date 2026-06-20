"""Synthesis entry point for the 4-bit adder.

synth_adder4() returns the lowered, buildable Netlist (NOR / CONST only). Running this
file as a script writes both the structural netlist and the lowered one to synth/out/:

    python synth/synth.py
      -> synth/out/adder4.json       (structural, readable gate types)
      -> synth/out/adder4_nor.json   (lowered to {NOR, CONST0, CONST1}, buildable)

The structural builder in hdl/adder.py is the verified synthesis path and needs no external
tools. When a full yosys (from oss-cad-suite) is installed, running this script ALSO runs the
proper verilog -> techmap -> NOR flow (synth/yosys_synth.py, script synth/adder4.ys) and
confirms its netlist is equivalent to this Python flow. When yosys is absent, the Python flow
stands alone and the NOR lowering is done by Netlist.to_nor(). See synth/adder4.ys for details.
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

    # Proper full-yosys path, when a complete yosys is installed. Confirms the real
    # verilog -> techmap -> NOR synthesis is equivalent to the Python flow above. Skipped
    # cleanly when yosys is absent (the Python flow is the verified default).
    try:
        from yosys_synth import find_yosys, synth_adder4_yosys
        from netlist import equivalent
        if find_yosys() is not None:
            yl, ypath = synth_adder4_yosys()
            print("wrote", ypath, f"(real yosys techmap, {yl.stats()['_total_cells']} cells)")
            print("yosys NOR netlist equivalent to Python flow:", equivalent(lowered, yl))
        else:
            print("full yosys not found; Python flow is the verified path (see synth/adder4.ys).")
    except Exception as e:  # never let the optional cross-check break the core synth
        print("yosys cross-check skipped:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
