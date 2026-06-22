"""Real-yosys synthesis path for SEQUENTIAL openttdoom designs (the counter).

This is the sequential counterpart of synth/yosys_synth.py. Where that one reads a
combinational verilog adder and techmaps it to NOR, this one reads a CLOCKED verilog counter
(emitted from the behavioural amaranth Counter via m.d.sync) and techmaps it to the buildable
register + NOR set: the flip-flops become $_DFF_P_ cells (positive-edge D flip-flops), which
import straight onto the netlist DFF register cell, and the combinational next-state logic
becomes $_NOR_ / $_NOT_, which import as NOR.

The key yosys step is `dfflegalize -cell $_DFF_P_ 0`: amaranth's m.d.sync register comes out
of `proc` as a synchronous-reset flop with a clock enable ($_SDFFE_*). dfflegalize lowers it
to a PLAIN positive-edge D flip-flop by pushing the enable and the reset into combinational
logic feeding D (a mux that re-loads Q when the flop is meant to hold, and forces 0 on reset).
That plain $_DFF_P_ is exactly our DFF cell: data D, clock C, output Q, no built-in enable or
async reset. abc then maps the combinational cone (including those muxes) to NOR, with
`-dff -keepff` so the flops are preserved across the abc pass.

yosys is OPTIONAL. find_yosys (reused from yosys_synth) returns None when no full yosys is
present, and callers fall back to the verified tool-free structural build_counter. When yosys
IS present, the imported netlist is checked sequential_equivalent to the structural counter
over an input trace.

The imported netlist carries amaranth's synchronous-reset port `rst` as an extra primary
input (the sync domain adds it). It is held 0 to compare against the structural counter, which
has no reset port; with rst == 0 the lowered $_DFF_P_ + NOR logic is the same up-counter.

stdlib + the netlist contract; amaranth only to emit verilog.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netlist import Netlist, Cell, Ports  # noqa: E402
from yosys_synth import find_yosys, prepare_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def emit_counter_verilog(out_v: str, width: int = 2) -> str:
    """Emit the behavioural Counter as verilog (via amaranth). Returns the path written."""
    sys.path.insert(0, os.path.join(REPO, "hdl"))
    from amaranth.back import verilog
    from sequential import Counter
    d = Counter(width)
    ports = [d.en, d.q]
    text = verilog.convert(d, ports=ports, name="counter")
    with open(out_v, "w") as f:
        f.write(text)
    return out_v


def run_yosys_seq(yosys_path: str, verilog_path: str, out_json: str,
                  top: str = "counter") -> None:
    """Run verilog -> ($_DFF_P_ + NOR/NOT) synthesis, writing a yosys JSON netlist.

    dfflegalize forces every flop to a plain positive-edge D flip-flop (enable and reset
    pushed into D's logic); abc -g NOR -dff -keepff maps the combinational cone to NOR while
    preserving the flops.
    """
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    script = (
        f"read_verilog {verilog_path}; "
        f"hierarchy -check -top {top}; "
        "proc; flatten; opt; techmap; opt; "
        "dfflegalize -cell $_DFF_P_ 0; "   # all flops -> plain pos-edge DFF, enable/rst into D
        "abc -g NOR -dff -keepff; "        # comb cone -> NOR, keep the flops
        "opt_clean; "
        f"write_json {out_json}; stat"
    )
    env = prepare_env(yosys_path)
    proc = subprocess.run([yosys_path, "-q", "-p", script],
                          env=env, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(out_json):
        raise RuntimeError(
            f"yosys (seq) failed (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}")


def import_yosys_seq(json_path: str, top: str = "counter") -> Netlist:
    """Parse a yosys JSON netlist of $_DFF_P_ / $_NOR_ / $_NOT_ cells into our Netlist.

    $_DFF_P_ (C=clock, D=data, Q=output) imports as our sequential DFF cell, with the clock
    net carried on Cell.clock. $_NOT_ is a one-input NOR; $_NOR_ a two-input NOR. Multi-bit
    ports (q[1:0]) expand to per-bit net names q0..q1 (LSB first); constants 0/1 tie cells.
    """
    d = json.load(open(json_path))
    mod = d["modules"][top]
    name: dict = {}
    inputs, outputs = [], []
    for p, info in mod["ports"].items():
        bits = info["bits"]
        w = len(bits)
        for i, b in enumerate(bits):
            nm = p if w == 1 else f"{p}{i}"
            name[b] = nm
            (inputs if info["direction"] == "input" else outputs).append(nm)

    def netof(bit):
        if bit in ("0", "1"):
            return "__const0" if bit == "0" else "__const1"
        return name.get(bit, f"n{bit}")

    cells = []
    used_const = set()
    for cn, cell in mod["cells"].items():
        t = cell["type"]
        conn = cell["connections"]
        cid = cn.replace("$", "_").replace("\\", "").replace(":", "_").replace(".", "_")
        if t == "$_DFF_P_":
            d_net = netof(conn["D"][0])
            clk = netof(conn["C"][0])
            q = netof(conn["Q"][0])
            cells.append(Cell(id=cid, type="DFF", inputs=[d_net], output=q,
                              clock=clk, reset=0))
            for n in (d_net, clk):
                if n.startswith("__const"):
                    used_const.add(n)
            continue
        if t == "$_NOR_":
            ins = [netof(conn["A"][0]), netof(conn["B"][0])]
            out = netof(conn["Y"][0])
        elif t == "$_NOT_":
            ins = [netof(conn["A"][0])]
            out = netof(conn["Y"][0])
        else:
            raise ValueError(
                f"unexpected yosys cell type {t} (expected $_DFF_P_/$_NOR_/$_NOT_)")
        for n in ins:
            if n.startswith("__const"):
                used_const.add(n)
        cells.append(Cell(id=cid, type="NOR", inputs=ins, output=out))

    if "__const0" in used_const:
        cells.append(Cell("tie0", "CONST0", [], "__const0"))
    if "__const1" in used_const:
        cells.append(Cell("tie1", "CONST1", [], "__const1"))
    nl = Netlist(name="counter_yosys", cells=cells, ports=Ports(inputs, outputs))
    nl.validate()
    return nl


def synth_counter_yosys(width: int = 2) -> Optional[Tuple[Netlist, str]]:
    """Full real-yosys path: emit counter verilog, synth to DFF + NOR, import.

    Returns (netlist, json_path) or None if no yosys is reachable.
    """
    yosys = find_yosys()
    if yosys is None:
        return None
    v = emit_counter_verilog(os.path.join(HERE, "counter.v"), width=width)
    out = os.path.join(HERE, "out", "counter_nor_yosys.json")
    run_yosys_seq(yosys, v, out)
    return import_yosys_seq(out), out


if __name__ == "__main__":
    res = synth_counter_yosys(2)
    if res is None:
        print("yosys not found; the verified path is the structural build_counter "
              "(see hdl/sequential.py).")
        sys.exit(0)
    yl, out = res
    print(f"real yosys (sequential) -> {out}")
    print(f"  cells: {yl.stats()}")
    print(f"  is_sequential: {yl.is_sequential()}  clocks: {yl.clocks()}")

    # quick self-check: compare to the structural counter over a trace, holding rst = 0.
    sys.path.insert(0, os.path.join(REPO, "hdl"))
    import random
    from netlist import simulate_trace
    from sequential import build_counter, counter_reference

    struct = build_counter(2)
    rng = random.Random(0)
    en_trace = [rng.randint(0, 1) for _ in range(24)]
    ref = counter_reference(en_trace, 2)

    # the yosys netlist has an extra 'rst' input; drive it 0.
    yl_trace = [{"en": e, "rst": 0} for e in en_trace]
    yl_rows = simulate_trace(yl, yl_trace, clock="clk")
    yl_q = [sum((r[f"q{i}"] << i) for i in range(2)) for r in yl_rows]
    st_rows = simulate_trace(struct, [{"en": e} for e in en_trace], clock="clk")
    st_q = [sum((r[f"q{i}"] << i) for i in range(2)) for r in st_rows]

    print(f"  structural matches reference: {st_q == ref}")
    # the yosys flop has a real sync reset to 0, so (unlike the structural feedback counter)
    # it powers on at 0 too: it should match the reference exactly, no phase offset.
    print(f"  yosys matches reference:      {yl_q == ref}")
