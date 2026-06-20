"""Cross-check the real-yosys ALU NOR synthesis against the golden CHIP-8 interpreter.

Runs only when a full yosys (oss-cad-suite) is installed, skips otherwise. The structural
Python ALU flow (hdl/test_alu.py) is the verified default that needs no external tools.
"""
import pytest

from yosys_alu import synth_alu8_yosys, errors
from yosys_synth import find_yosys
from netlist import BUILDABLE

pytestmark = pytest.mark.skipif(
    find_yosys() is None, reason="full yosys (oss-cad-suite) not installed")


def test_yosys_alu_techmap_computes_all_ops():
    nl, _ = synth_alu8_yosys()
    assert set(c.type for c in nl.cells) <= BUILDABLE
    assert errors(nl) == 0
