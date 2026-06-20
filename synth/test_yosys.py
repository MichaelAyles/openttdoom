"""Cross-check the real-yosys NOR synthesis against the verified Python flow.

Runs only when a full yosys (oss-cad-suite) is installed, and skips cleanly otherwise, since
the structural Python flow (Netlist.to_nor) is the verified default that needs no external
tools. When yosys IS present, this proves the proper verilog -> techmap -> NOR path produces
a netlist that adds correctly and is equivalent to the Python flow.
"""
import pytest

from yosys_synth import find_yosys, synth_adder4_yosys
from netlist import equivalent, BUILDABLE
from adder import build_adder4_netlist

pytestmark = pytest.mark.skipif(
    find_yosys() is None, reason="full yosys (oss-cad-suite) not installed")


def _add_errors(nl) -> int:
    bad = 0
    for a in range(16):
        for b in range(16):
            for cin in (0, 1):
                t = a + b + cin
                exp = {**{f"s{i}": (t >> i) & 1 for i in range(4)}, "cout": (t >> 4) & 1}
                iv = {**{f"a{i}": (a >> i) & 1 for i in range(4)},
                      **{f"b{i}": (b >> i) & 1 for i in range(4)}, "cin": cin}
                if nl.outputs_for(iv) != exp:
                    bad += 1
    return bad


def test_yosys_nor_techmap_matches_python_flow():
    yl, _ = synth_adder4_yosys()
    # only buildable cells (NOR; NOT imported as a one-input NOR)
    assert set(c.type for c in yl.cells) <= BUILDABLE
    # it actually adds
    assert _add_errors(yl) == 0
    # and it is the same function as the Python NOR lowering
    py = build_adder4_netlist().to_nor()
    assert equivalent(py, yl)
