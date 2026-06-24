"""Generic fresh-server runner for the FIXED-NETWORK gate scenarios.

Reuses run_sc1's configure/launch/poll plumbing but is GS-agnostic: point it at a
game-dir name + a main.nut/info.nut source dir, set the [game_scripts] entry to that
GS's GetName, launch a fresh dedicated server, start_ai Idle, and poll the company
name until a line matching --prefix appears (or timeout). Prints every distinct
company-name readout so the per-combo readouts are visible.

This does NOT compute anything in Python; it only relays the company name the GS sets
(the GS encodes raw reader x). The judge is external (the operator reads the raw x).

Usage:
  python tools/run_fixed.py --gsname stageA --gsdir stageA_gs --prefix "XNOR" [--timeout 360] [--runs 4]
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

import run_sc1 as sc1  # configure(), set_cfg(), _wait_port(), OTTD_EXE/DIR, PERSONAL  # noqa: E402
from ottd_admin import AdminClient  # noqa: E402

PERSONAL = sc1.PERSONAL


def select_gs(gsname: str) -> None:
    """Point openttd.cfg [game_scripts] at a single entry = gsname (the GS GetName)."""
    cfg = os.path.join(PERSONAL, "openttd.cfg")
    text = open(cfg, encoding="utf-8", errors="replace").read().split("\n")
    out, in_sec, wrote = [], False, False
    for ln in text:
        s = ln.strip()
        if s.startswith("["):
            if in_sec and not wrote:
                out.append(f"{gsname} =")
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
        out.append(f"{gsname} =")
    elif not wrote:
        out.append("[game_scripts]")
        out.append(f"{gsname} =")
    open(cfg, "w", encoding="utf-8").write("\n".join(out))


def install_gs(gsdir: str) -> None:
    src = os.path.join(REPO, "scenarios", gsdir)
    dst = os.path.join(PERSONAL, "game", gsdir)
    os.makedirs(dst, exist_ok=True)
    for f in ("info.nut", "main.nut"):
        open(os.path.join(dst, f), "w", encoding="utf-8").write(
            open(os.path.join(src, f), encoding="utf-8").read())


def _kill() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "openttd.exe"], capture_output=True)
    time.sleep(2)


def run_once(prefix: str, timeout: int, min_fields: int) -> str:
    _kill()
    subprocess.Popen([sc1.OTTD_EXE, "-D", "-d", "script=1"], cwd=sc1.OTTD_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not sc1._wait_port():
        print("  admin port did not open")
        return ""
    state = {"c": AdminClient()}
    state["c"].connect()
    state["c"].rcon("start_ai Idle")

    def company_name() -> str:
        # Reconnect on a transient admin-socket reset (only ONE admin connection at a time;
        # a reset must not mask the readout, so we rebuild the client and retry once).
        for attempt in range(2):
            try:
                for l in state["c"].rcon("companies"):
                    m = re.search(r"Company Name: '([^']*)'", l)
                    if m:
                        return m.group(1)
                return ""
            except (OSError, Exception):
                try:
                    state["c"].close()
                except Exception:
                    pass
                time.sleep(1)
                try:
                    state["c"] = AdminClient()
                    state["c"].connect()
                except Exception:
                    return ""
        return ""

    final, last, t0 = "", "", time.time()
    while time.time() - t0 < timeout:
        nm = company_name()
        if nm and nm != last:
            print(f"    +{int(time.time()-t0)}s '{nm}'", flush=True)
            last = nm
        if nm:
            final = nm
            if nm.startswith(prefix) and len(nm.split()) >= min_fields:
                break
            if "CKFAIL" in nm or "ERR" in nm:
                break
        time.sleep(4)
    try:
        state["c"].close()
    except Exception:
        pass
    time.sleep(1)
    _kill()
    return final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsname", required=True)
    ap.add_argument("--gsdir", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--timeout", type=int, default=360)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--minfields", type=int, default=2)
    ap.add_argument("--map", type=int, default=8)
    a = ap.parse_args()
    sc1.configure(map_log2=a.map)
    select_gs(a.gsname)
    install_gs(a.gsdir)
    results = []
    for r in range(1, a.runs + 1):
        print(f"########## RUN {r}/{a.runs} {time.strftime('%H:%M:%S')} ##########", flush=True)
        out = run_once(a.prefix, a.timeout, a.minfields)
        print(f"########## RUN {r} RESULT: {out} ##########", flush=True)
        results.append(out)
    print("==== ALL RESULTS ====")
    for i, r in enumerate(results, 1):
        print(f"  run {i}: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
