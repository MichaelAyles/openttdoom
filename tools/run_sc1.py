"""SC1 driver: emit a ONE-CELL NOR2 placement and run it through the computecell GS.

This is the fusion check. It builds a single-cell NOR2 netlist (primary inputs a, b,
primary output y), runs it through the real place_and_route (place + emit), writes the
emitted placement as the GameScript's scenario_data.nut, then starts a dedicated OpenTTD
server, founds a company (start_ai), and polls the company name until the computecell GS
has stamped the cell FROM THE PLACEMENT and swept the four input combos. The four raw
reader x are read out of the company name; NOR = 1,0,0,0 is judged externally from
x > SIGX, never computed in Squirrel from the inputs.

Usage:
  python tools/run_sc1.py [--timeout 240]
prints the final company-name readout line (e.g. "SC1 s19 25 19 19 19").
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
for d in ("synth", "place_and_route", "hdl", "scenarios"):
    sys.path.insert(0, os.path.join(REPO, d))

from ottd_admin import AdminClient  # noqa: E402
from netlist import Netlist, Cell, Ports  # noqa: E402
from emit import build_scenario  # noqa: E402

OTTD_DIR = os.path.join(REPO, "vendor", "openttd", "openttd-15.3-windows-win64")
OTTD_EXE = os.path.join(OTTD_DIR, "openttd.exe")
PERSONAL = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "OpenTTD")
if not os.path.isdir(PERSONAL):
    PERSONAL = os.path.join(os.path.expanduser("~"), "Documents", "OpenTTD")

GS_NAME = "computecell"
GS_DIR = "computecell_gs"


def set_cfg(path: str, section: str, key: str, value: str) -> None:
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    out, in_sec, done = [], False, False
    for ln in lines:
        s = ln.strip()
        if s.startswith("["):
            if in_sec and not done:
                out.append(f"{key} = {value}")
                done = True
            in_sec = (s == f"[{section}]")
        if in_sec and re.match(rf"^{re.escape(key)}\s*=", s):
            out.append(f"{key} = {value}")
            done = True
            continue
        out.append(ln)
    if not done:
        out.append(f"[{section}]")
        out.append(f"{key} = {value}")
    open(path, "w", encoding="utf-8").write("\n".join(out))


def select_gs() -> None:
    """Point openttd.cfg at the computecell GS and remove any other game_scripts entry."""
    cfg = os.path.join(PERSONAL, "openttd.cfg")
    text = open(cfg, encoding="utf-8", errors="replace").read().split("\n")
    out, in_sec, wrote = [], False, False
    for ln in text:
        s = ln.strip()
        if s.startswith("["):
            if in_sec and not wrote:
                out.append(f"{GS_NAME} =")
                wrote = True
            in_sec = (s == "[game_scripts]")
            out.append(ln)
            continue
        if in_sec:
            # drop every existing entry inside [game_scripts]; we write our single one.
            if s == "" or s.startswith(";"):
                out.append(ln)
            continue
        out.append(ln)
    if in_sec and not wrote:
        out.append(f"{GS_NAME} =")
    elif not wrote:
        out.append("[game_scripts]")
        out.append(f"{GS_NAME} =")
    open(cfg, "w", encoding="utf-8").write("\n".join(out))


def configure(map_log2: int = 8, admin_pw: str = "ottdoom") -> None:
    cfg = os.path.join(PERSONAL, "openttd.cfg")
    sec = os.path.join(PERSONAL, "secrets.cfg")
    set_cfg(sec, "network", "admin_password", admin_pw)
    set_cfg(cfg, "network", "allow_insecure_admin_login", "true")
    set_cfg(cfg, "network", "server_admin_port", "3977")
    set_cfg(cfg, "difficulty", "terrain_type", "0")
    set_cfg(cfg, "difficulty", "number_towns", "0")
    set_cfg(cfg, "difficulty", "industry_density", "0")
    set_cfg(cfg, "difficulty", "max_loan", "2000000000")
    set_cfg(cfg, "game_creation", "amount_of_rivers", "0")
    set_cfg(cfg, "game_creation", "water_borders", "0")
    set_cfg(cfg, "game_creation", "map_x", str(map_log2))
    set_cfg(cfg, "game_creation", "map_y", str(map_log2))
    select_gs()


def emit_sc1() -> str:
    """Build the one-cell NOR2 placement and install it as scenario_data.nut. Returns SIGX."""
    nl = Netlist("sc1", [Cell("g0", "NOR", ["a", "b"], "y")], Ports(["a", "b"], ["y"]))
    nl.validate()
    scen, rr = build_scenario(nl)
    cell = scen.cells[0]
    sigx = cell.x + 7
    # Install the emitted placement for the GS to read.
    dst = os.path.join(PERSONAL, "game", GS_DIR, "scenario_data.nut")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8").write(scen.to_nut())
    # Mirror the GS source into the game dir (info.nut + main.nut) so the latest runs.
    src = os.path.join(REPO, "scenarios", GS_DIR)
    for f in ("info.nut", "main.nut"):
        open(os.path.join(PERSONAL, "game", GS_DIR, f), "w", encoding="utf-8").write(
            open(os.path.join(src, f), encoding="utf-8").read())
    print(f"emitted SC1: cell origin ({cell.x},{cell.y}) taps "
          f"{[(p.x, p.y) for p in cell.inputs]} out ({cell.output.x},{cell.output.y}) "
          f"sigx={sigx} routed {rr.coverage()[0]}/{rr.coverage()[1]}")
    return sigx


def _kill() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "openttd.exe"], capture_output=True)
    time.sleep(2)


def _wait_port(port: int = 3977, secs: int = 25) -> bool:
    for _ in range(secs):
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            return True
        except OSError:
            time.sleep(1)
    return False


def run(timeout: int = 240) -> str:
    _kill()
    subprocess.Popen([OTTD_EXE, "-D", "-d", "script=1"], cwd=OTTD_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait_port():
        print("admin port did not open")
        return ""
    c = AdminClient()
    c.connect()
    c.rcon("start_ai")

    def company_name() -> str:
        for l in c.rcon("companies"):
            m = re.search(r"Company Name: '([^']*)'", l)
            if m:
                return m.group(1)
        return ""

    final = ""
    t0 = time.time()
    while time.time() - t0 < timeout:
        nm = company_name()
        if nm:
            print(f"  t={int(time.time()-t0)}s name='{nm}'", flush=True)
            final = nm
            if nm.startswith("SC1 s") and len(nm.split()) >= 6:
                # full readout latched (signal x + 4 combo x)
                break
        time.sleep(6)
    c.close()
    time.sleep(1)
    _kill()
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--map", type=int, default=8)
    a = ap.parse_args()
    configure(map_log2=a.map)
    emit_sc1()
    print("running SC1 in OpenTTD (dedicated headless build) ...")
    readout = run(timeout=a.timeout)
    print("READOUT:", readout)
    return 0 if readout.startswith("SC1 s") else 1


if __name__ == "__main__":
    raise SystemExit(main())
