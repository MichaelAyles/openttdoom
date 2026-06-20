"""Make the toolchain modules importable by their bare names from any test.

pytest auto-loads this from the repo root, so tests can do `from netlist import ...`,
`from scenario import ...`, `from chip8 import ...` without path juggling.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
for _d in ("synth", "place_and_route", "hdl", "golden", "scenarios"):
    _p = os.path.join(ROOT, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
