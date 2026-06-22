"""Synthesis entry point for the SEQUENTIAL worked examples (toggle and counter).

The sequential counterpart of synth/synth.py. It writes the structural register + NOR
netlists and their buildable lowerings to synth/out/:

    python synth/synth_seq.py
      -> synth/out/toggle.json        (structural: a DFF + NOT toggle flip-flop)
      -> synth/out/toggle_nor.json    (lowered to {NOR, CONST0, CONST1} + latch feedback)
      -> synth/out/counter.json       (structural: 2-bit up counter, DFFs + incrementer)
      -> synth/out/counter_nor.json   (lowered, buildable)

The structural builders in hdl/sequential.py are the verified, tool-free synthesis path. When
a full yosys (oss-cad-suite) is installed, this script ALSO runs the proper verilog -> $_DFF_P_
+ NOR flow (synth/yosys_seq.py) and confirms the yosys counter computes the same up-count as
the structural build over an input trace. When yosys is absent, the structural flow stands
alone and the NOR lowering is done by Netlist.to_nor().
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _d in (_HERE, os.path.join(_ROOT, "hdl")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from netlist import Netlist, simulate_trace  # noqa: E402
from sequential import (  # noqa: E402
    build_counter,
    build_toggle_ff,
    counter_reference,
)


def _out_dir() -> str:
    d = os.path.join(_HERE, "out")
    os.makedirs(d, exist_ok=True)
    return d


def synth_toggle() -> Netlist:
    """The lowered, buildable toggle flip-flop netlist (NOR / CONST only + latch feedback)."""
    return build_toggle_ff().to_nor()


def synth_counter(width: int = 2) -> Netlist:
    """The lowered, buildable up-counter netlist (NOR / CONST only + latch feedback)."""
    return build_counter(width).to_nor()


def main() -> int:
    out = _out_dir()
    width = 2

    toggle = build_toggle_ff()
    counter = build_counter(width)
    toggle_nor = toggle.to_nor()
    counter_nor = counter.to_nor()

    for nl, fn in (
        (toggle, "toggle.json"),
        (toggle_nor, "toggle_nor.json"),
        (counter, "counter.json"),
        (counter_nor, "counter_nor.json"),
    ):
        p = os.path.join(out, fn)
        nl.save(p)
        print("wrote", p, f"({nl.stats()['_total_cells']} cells, "
              f"sequential={nl.is_sequential()})")

    # structural counter is correct against the behavioural reference over a trace.
    en_trace = [1, 1, 1, 1, 0, 1, 1, 0, 1, 1]
    rows = simulate_trace(counter, [{"en": e} for e in en_trace], clock="clk")
    got = [sum((r[f"q{i}"] << i) for i in range(width)) for r in rows]
    ref = counter_reference(en_trace, width)
    print("structural counter computes the reference up-count:", got == ref, got)

    # Optional full-yosys sequential path, when a complete yosys is installed.
    try:
        from yosys_seq import synth_counter_yosys
        res = synth_counter_yosys(width)
        if res is None:
            print("full yosys not found; structural flow is the verified path.")
        else:
            yl, ypath = res
            yl_rows = simulate_trace(
                yl, [{"en": e, **({"rst": 0} if "rst" in yl.ports.inputs else {})}
                     for e in en_trace], clock="clk")
            yl_q = [sum((r[f"q{i}"] << i) for i in range(width)) for r in yl_rows]
            print("wrote", ypath, f"(real yosys, {yl.stats()['_total_cells']} cells, "
                  f"DFF={yl.stats().get('DFF', 0)})")
            print("yosys counter matches the reference up-count:", yl_q == ref)
    except Exception as e:  # never let the optional cross-check break the core synth
        print("yosys sequential cross-check skipped:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
