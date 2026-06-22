"""Driver for the clocked 1-bit REGISTER GS (scenarios/register_gs).

Installs the register GS into the OpenTTD game dir, points openttd.cfg at it, starts a
fresh dedicated headless server, founds a company (start_ai), and polls the company name
until the GS reports its per-edge reads and the final "RG <7 bits>" readout.

The register holds a bit as a parked-train presence on a HOLD tile and reads it back per
clock edge. Schedule W1,-,-,W0,- -> expected read-back Q = 1,1,1,0,0 == RG 11100.
Every bit is judged from the RAW reader x (q = held at RSIGX), never from a Squirrel flag.

Usage: python tools/run_register.py [--timeout 360] [--runs 1]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import run_sc1 as base  # reuse set_cfg / configure plumbing  # noqa: E402

GS_NAME = "register"
GS_DIR = "register_gs"


def select_register_gs() -> None:
    """Point openttd.cfg [game_scripts] at the register GS only."""
    cfg = os.path.join(base.PERSONAL, "openttd.cfg")
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


def install_gs() -> None:
    src = os.path.join(REPO, "scenarios", GS_DIR)
    dst = os.path.join(base.PERSONAL, "game", GS_DIR)
    os.makedirs(dst, exist_ok=True)
    for f in ("info.nut", "main.nut"):
        shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))
    print(f"installed {GS_DIR} -> {dst}")


def run(timeout: int) -> str:
    base._kill()
    import subprocess, socket
    subprocess.Popen([base.OTTD_EXE, "-D", "-d", "script=1"], cwd=base.OTTD_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not base._wait_port():
        print("admin port did not open")
        return ""
    from ottd_admin import AdminClient
    c = AdminClient()
    c.connect()
    # Found the company with the IDLE AI explicitly (it just founds a company and does
    # nothing). A bare `start_ai` picks a RANDOM AI here, and sometimes lands on LoopBench,
    # which floods the map with ~190 benchmark trains. Those do not touch the register lane
    # (the result is still RG 11100), but Idle keeps each run clean and deterministic.
    c.rcon("start_ai Idle")

    def company_name() -> str:
        for l in c.rcon("companies"):
            m = re.search(r"Company Name: '([^']*)'", l)
            if m:
                return m.group(1)
        return ""

    final, last, t0 = "", "", time.time()
    while time.time() - t0 < timeout:
        nm = company_name()
        if nm and nm != last:
            print(f"  t={int(time.time()-t0)}s name='{nm}'", flush=True)
            last = nm
        if nm:
            final = nm
            if re.match(r"^RG [01]{5}", nm):
                break
            if "CKFAIL" in nm:
                break
        time.sleep(4)
    c.close()
    time.sleep(1)
    base._kill()
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=360)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--map", type=int, default=8)
    a = ap.parse_args()
    base.configure(map_log2=a.map)
    select_register_gs()
    install_gs()
    results = []
    for r in range(a.runs):
        print(f"===== RUN {r+1}/{a.runs} =====", flush=True)
        readout = run(a.timeout)
        print("READOUT:", readout, flush=True)
        results.append(readout)
    print("ALL RESULTS:", results)
    return 0 if any(re.match(r"^RG [01]{5}", x or "") for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
