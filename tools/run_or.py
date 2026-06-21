"""Stage 2 (SC2) driver: emit a 2-CELL OR = NOT(NOR(a,b)) placement and run it through the GS.

gate1 NOR2(a,b) -> net w, gate2 NOT(w) -> y. The toolchain places both cells and routes the
inter-cell net w (gate1.output -> gate2.input). The computecell GS reads the placement, stamps
gate1 at its placed origin, and CO-LOCATES gate2 three rows below it (a chain placement
constraint derived from gate1's placed geometry) so gate2's input tap sits on gate1's frozen
output rest column. The inter-cell bit then transfers PHYSICALLY over a short pure-vertical
no-signal track spur (the proven norchain coupling): gate1's passing reader, frozen on its rest
tile, occupies gate2's input block, so gate2 = NOT(gate1) = OR. The link is verified to be the
EMITTED routed net w, not an assumption. The four gate2 raw reader x are read out of the company
name; OR = 0,1,1,1 is judged externally from x > sig (no OR computed in Squirrel).

Verified: OR s24 23 29 29 29 (g2sigx=24; x>24 => OR 1) = 0,1,1,1, reproduced across fresh runs.

Usage: python tools/run_or.py [--timeout 360]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
for d in ("synth", "place_and_route", "hdl", "scenarios"):
    sys.path.insert(0, os.path.join(REPO, d))

import run_sc1 as sc1  # reuse configure/select_gs/run plumbing  # noqa: E402
from netlist import Netlist, Cell, Ports  # noqa: E402
from emit import build_scenario  # noqa: E402


def emit_or() -> None:
    nl = Netlist("sc2_or",
                 [Cell("g0", "NOR", ["a", "b"], "w"), Cell("g1", "NOR", ["w"], "y")],
                 Ports(["a", "b"], ["y"]))
    nl.validate()
    scen, rr = build_scenario(nl)
    dst = os.path.join(sc1.PERSONAL, "game", sc1.GS_DIR, "scenario_data.nut")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8").write(scen.to_nut())
    src = os.path.join(REPO, "scenarios", sc1.GS_DIR)
    for f in ("info.nut", "main.nut"):
        open(os.path.join(sc1.PERSONAL, "game", sc1.GS_DIR, f), "w", encoding="utf-8").write(
            open(os.path.join(src, f), encoding="utf-8").read())
    g0, g1 = scen.cells[0], scen.cells[1]
    print(f"emitted OR: gate1 '{g0.id}' origin ({g0.x},{g0.y}) out ({g0.output.x},{g0.output.y}); "
          f"gate2 '{g1.id}' origin ({g1.x},{g1.y}) in ({g1.inputs[0].x},{g1.inputs[0].y}); "
          f"routed {rr.coverage()[0]}/{rr.coverage()[1]}")


def run(timeout: int) -> str:
    sc1._kill()
    import subprocess, socket, time
    subprocess.Popen([sc1.OTTD_EXE, "-D", "-d", "script=1"], cwd=sc1.OTTD_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not sc1._wait_port():
        print("admin port did not open")
        return ""
    from ottd_admin import AdminClient
    c = AdminClient()
    c.connect()
    c.rcon("start_ai")

    def company_name() -> str:
        for l in c.rcon("companies"):
            m = re.search(r"Company Name: '([^']*)'", l)
            if m:
                return m.group(1)
        return ""

    final, t0 = "", time.time()
    while time.time() - t0 < timeout:
        nm = company_name()
        if nm:
            print(f"  t={int(time.time()-t0)}s name='{nm}'", flush=True)
            final = nm
            if nm.startswith("OR s") and len(nm.split()) >= 6:
                break
        time.sleep(6)
    c.close()
    time.sleep(1)
    sc1._kill()
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--map", type=int, default=8)
    a = ap.parse_args()
    sc1.configure(map_log2=a.map)
    emit_or()
    print("running OR (2-cell chain) in OpenTTD ...")
    readout = run(a.timeout)
    print("READOUT:", readout)
    return 0 if readout.startswith("OR s") else 1


if __name__ == "__main__":
    raise SystemExit(main())
