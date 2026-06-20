"""Real-yosys synthesis path for the openttdoom 4-bit adder.

This is the "proper" synthesis the brief asked for: read a verilog adder, run yosys, and
techmap it down to the buildable NOR / NOT cell set (NOT is a one-input NOR). It is the
counterpart to the self-contained Python flow (hdl.adder.build_adder4_netlist +
Netlist.to_nor): both produce a buildable NOR netlist, and we check they are equivalent.

yosys is OPTIONAL. If a full yosys (from oss-cad-suite) is not found, find_yosys returns
None and callers fall back to the verified Python flow. When yosys IS found, run_yosys_nor
emits the netlist and we confirm it equals the Python result over the full truth table.

Notes on this environment:
  - yosys is a native Windows exe and needs its bundled DLLs (oss-cad-suite/lib) on PATH and
    a clean TEMP, both of which prepare_env sets up.
  - The NOR mapping uses abc's built-in gate set (abc -g NOR) rather than the liberty file in
    synth/nor.lib, because this yosys build's liberty-to-genlib conversion fails on Windows
    (it logs "merged SCL conversion failed"). abc -g NOR yields the same buildable {NOR, NOT}
    result. synth/nor.lib and synth/adder4.ys document the liberty path for other yosys builds.

stdlib + the netlist contract only. amaranth is used only to emit the verilog.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netlist import Netlist, Cell, Ports, equivalent, BUILDABLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def find_yosys() -> Optional[str]:
    """Locate a full yosys.exe (the oss-cad-suite build), or None.

    Search order: $OSS_CAD_SUITE_ROOT, common install locations outside the repo (kept out
    of the repo tree on purpose, the suite is ~2 GB), then PATH. The repo is gitignored under
    vendor/, but the suite is intentionally NOT placed there: this tree often lives in a
    cloud-synced folder and 2 GB does not belong in it. setup.sh documents the install.
    """
    candidates = []
    env_root = os.environ.get("OSS_CAD_SUITE_ROOT")
    if env_root:
        candidates.append(os.path.join(env_root, "bin", "yosys.exe"))
    home = os.path.expanduser("~")
    candidates += [
        os.path.join(home, "ossbuild", "oss-cad-suite", "bin", "yosys.exe"),
        os.path.join(home, "oss-cad-suite", "bin", "yosys.exe"),
        os.path.join("C:\\", "oss-cad-suite", "bin", "yosys.exe"),
        os.path.join(REPO, "vendor", "oss-cad-suite", "bin", "yosys.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # PATH fallback (covers Linux/macOS oss-cad-suite or a system install).
    from shutil import which
    return which("yosys")


def prepare_env(yosys_path: str) -> dict:
    """Env for running yosys: its lib/ on PATH for DLLs, plus a clean TEMP for abc."""
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(yosys_path))   # .../oss-cad-suite
    binp = os.path.join(root, "bin")
    libp = os.path.join(root, "lib")
    env["PATH"] = binp + os.pathsep + libp + os.pathsep + env.get("PATH", "")
    tmp = os.path.join(root, "_tmp")
    os.makedirs(tmp, exist_ok=True)
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = tmp
    return env


def emit_adder_verilog(out_v: str) -> str:
    """Emit the behavioural Adder4 as verilog (via amaranth). Returns the path written."""
    sys.path.insert(0, os.path.join(REPO, "hdl"))
    from amaranth.back import verilog
    from adder import Adder4
    d = Adder4()
    ports = [getattr(d, n) for n in ("a", "b", "cin", "s", "cout") if hasattr(d, n)]
    text = verilog.convert(d, ports=ports, name="adder4")
    with open(out_v, "w") as f:
        f.write(text)
    return out_v


def run_yosys_nor(yosys_path: str, verilog_path: str, out_json: str,
                  top: str = "adder4") -> None:
    """Run the verilog -> NOR/NOT synthesis, writing a yosys JSON netlist to out_json."""
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    script = (
        f"read_verilog {verilog_path}; "
        f"hierarchy -check -top {top}; "
        "proc; flatten; opt; techmap; opt; "
        "abc -g NOR; "          # built-in NOR+NOT cover, see module docstring
        "opt_clean; "
        f"write_json {out_json}; stat"
    )
    env = prepare_env(yosys_path)
    proc = subprocess.run([yosys_path, "-q", "-p", script],
                          env=env, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(out_json):
        raise RuntimeError(
            f"yosys failed (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}")


def import_yosys_nor(json_path: str, top: str = "adder4") -> Netlist:
    """Parse a yosys JSON netlist of $_NOR_/$_NOT_ cells into our Netlist.

    A one-input NOR is exactly NOT, so $_NOT_ imports as a NOR cell with one input. Multi-bit
    ports (a[3:0]) become per-bit net names a0..a3 (LSB first); constants 0/1 become tie cells.
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
        if t == "$_NOR_":
            ins = [netof(conn["A"][0]), netof(conn["B"][0])]
            out = netof(conn["Y"][0])
        elif t == "$_NOT_":
            ins = [netof(conn["A"][0])]      # one-input NOR == NOT
            out = netof(conn["Y"][0])
        else:
            raise ValueError(f"unexpected yosys cell type {t} (expected $_NOR_/$_NOT_)")
        for n in ins:
            if n.startswith("__const"):
                used_const.add(n)
        cells.append(Cell(id=cn.replace("$", "_").replace("\\", ""),
                          type="NOR", inputs=ins, output=out))
    if "__const0" in used_const:
        cells.append(Cell("tie0", "CONST0", [], "__const0"))
    if "__const1" in used_const:
        cells.append(Cell("tie1", "CONST1", [], "__const1"))
    nl = Netlist(name="adder4_yosys", cells=cells, ports=Ports(inputs, outputs))
    nl.validate()
    return nl


def synth_adder4_yosys() -> Optional[Tuple[Netlist, str]]:
    """Full real-yosys path: emit verilog, synth to NOR, import. None if yosys absent."""
    yosys = find_yosys()
    if yosys is None:
        return None
    v = emit_adder_verilog(os.path.join(HERE, "adder4.v"))
    out = os.path.join(HERE, "out", "adder4_nor_yosys.json")
    run_yosys_nor(yosys, v, out)
    return import_yosys_nor(out), out


if __name__ == "__main__":
    res = synth_adder4_yosys()
    if res is None:
        print("yosys not found (looked on PATH and known oss-cad-suite locations).")
        print("The verified synthesis path is the Python flow; see synth/synth.py.")
        sys.exit(0)
    yl, out = res
    print(f"real yosys -> {out}")
    print(f"  cells: {yl.stats()}  buildable-only: {set(c.type for c in yl.cells) <= BUILDABLE}")

    def expect(a, b, cin):
        t = a + b + cin
        return {**{f"s{i}": (t >> i) & 1 for i in range(4)}, "cout": (t >> 4) & 1}
    bad = 0
    for a in range(16):
        for b in range(16):
            for cin in (0, 1):
                iv = {**{f"a{i}": (a >> i) & 1 for i in range(4)},
                      **{f"b{i}": (b >> i) & 1 for i in range(4)}, "cin": cin}
                if yl.outputs_for(iv) != expect(a, b, cin):
                    bad += 1
    print(f"  computes a+b+cin: {512 - bad}/512 correct")
    py = Netlist.load(os.path.join(HERE, "out", "adder4_nor.json"))
    print(f"  equivalent to Python to_nor() flow: {equivalent(py, yl)} "
          f"(yosys {yl.stats()['_total_cells']} cells vs python {py.stats()['_total_cells']})")
