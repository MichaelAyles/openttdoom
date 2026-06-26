"""Adversarial single-combo full-adder verifier.

Builds ONE (a,b,cin) combo of the facombo GS per fresh SOLE-PROCESS server, then reads the
RAW reader x out of the company name. Judges sum/cout EXTERNALLY from raw x only
(sum x > Y_SIG=50 => 1; cout x > GM_SIG=40 => 1). Nothing is computed in Squirrel.

Unlike run_facombo.py, this also parses the LATCHED stream lines
    "FA<Y_SIG> <sum_x> c<abc>"   and   "FC<GM_SIG> <cout_x> c<abc>"
which the GS emits forever after the one-shot "c<abc> s<x> m<x>" line, so we never miss the
readout to a polling race. We accept whichever raw x we capture (per-combo line preferred,
else the latched FA/FC stream).

HARNESS RULE: sole process only. Hard-kills stray openttd FIRST, single server at a time.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import run_sc1 as sc1  # noqa: E402
import run_facombo as rf  # noqa: E402  (its select_gs/set_combo point at facombo, NOT computecell)
from ottd_admin import AdminClient  # noqa: E402

PERSONAL = sc1.PERSONAL
GS_NAME = "facombo"
GS_DIR = "facombo_gs"


def configure_map_only(map_log2: int = 8, admin_pw: str = "ottdoom") -> None:
    """Set the server/map/difficulty config WITHOUT touching [game_scripts] selection.
    (sc1.configure() would call sc1.select_gs() and clobber the GS back to computecell.)"""
    cfg = os.path.join(PERSONAL, "openttd.cfg")
    sec = os.path.join(PERSONAL, "secrets.cfg")
    sc1.set_cfg(sec, "network", "admin_password", admin_pw)
    sc1.set_cfg(cfg, "network", "allow_insecure_admin_login", "true")
    sc1.set_cfg(cfg, "network", "server_admin_port", "3977")
    sc1.set_cfg(cfg, "difficulty", "terrain_type", "0")
    sc1.set_cfg(cfg, "difficulty", "number_towns", "0")
    sc1.set_cfg(cfg, "difficulty", "industry_density", "0")
    sc1.set_cfg(cfg, "difficulty", "max_loan", "2000000000")
    sc1.set_cfg(cfg, "game_creation", "amount_of_rivers", "0")
    sc1.set_cfg(cfg, "game_creation", "water_borders", "0")
    sc1.set_cfg(cfg, "game_creation", "map_x", str(map_log2))
    sc1.set_cfg(cfg, "game_creation", "map_y", str(map_log2))

EXP_SUM = [0, 1, 1, 0, 1, 0, 0, 1]   # parity(a,b,cin)
EXP_COUT = [0, 0, 0, 1, 0, 1, 1, 1]  # majority(a,b,cin)
Y_SIG = 50
GM_SIG = 40


def install_gs(combo: int) -> None:
    src = os.path.join(REPO, "scenarios", GS_DIR)
    dst = os.path.join(PERSONAL, "game", GS_DIR)
    os.makedirs(dst, exist_ok=True)
    open(os.path.join(dst, "info.nut"), "w", encoding="utf-8").write(
        open(os.path.join(src, "info.nut"), encoding="utf-8").read())
    main = open(os.path.join(src, "main.nut"), encoding="utf-8").read()
    patched, n = re.subn(r"^COMBO_SEL <- \d+;", f"COMBO_SEL <- {combo};", main, count=1,
                         flags=re.MULTILINE)
    if n != 1:
        raise RuntimeError("could not rewrite COMBO_SEL")
    open(os.path.join(dst, "main.nut"), "w", encoding="utf-8").write(patched)


def kill() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "openttd.exe"], capture_output=True)
    time.sleep(2)


def run_combo(combo: int, timeout: int) -> dict:
    a, b, cin = (combo >> 2) & 1, (combo >> 1) & 1, combo & 1
    configure_map_only(map_log2=8)
    rf.select_gs()        # point [game_scripts] at facombo (NOT computecell)
    rf.set_combo(combo)   # cfg subsection (belt-and-suspenders)
    install_gs(combo)     # the reliable selector: rewrite COMBO_SEL in installed main.nut

    kill()
    subprocess.Popen([sc1.OTTD_EXE, "-D", "-d", "script=1"], cwd=sc1.OTTD_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not sc1._wait_port():
        kill()
        return {"combo": combo, "abc": f"{a}{b}{cin}", "s": -1, "m": -1, "br": None,
                "err": "no admin port"}
    c = AdminClient()
    c.connect()
    c.rcon("start_ai Idle")

    def company_name() -> str:
        for _ in range(2):
            try:
                for l in c.rcon("companies"):
                    mm = re.search(r"Company Name: '([^']*)'", l)
                    if mm:
                        return mm.group(1)
                return ""
            except Exception:
                time.sleep(1)
        return ""

    s, m, br = -1, -1, None
    last = ""
    t0 = time.time()
    saw_per_combo = False
    saw_fa = False
    saw_fc = False
    # collect until we have BOTH a sum x and a cout x (latched stream gives them in turn)
    while time.time() - t0 < timeout:
        nm = company_name()
        if nm and nm != last:
            print(f"    +{int(time.time()-t0)}s '{nm}'", flush=True)
            last = nm
        if nm:
            mb = re.match(r"^FA built1 b(\d)$", nm)
            if mb:
                br = int(mb.group(1))
            # one-shot per-combo line "c<abc> s<x> m<x>"
            pc = re.match(r"^c(\d)(\d)(\d) s(-?\d+) m(-?\d+)$", nm.strip())
            if pc:
                s = int(pc.group(4)); m = int(pc.group(5)); saw_per_combo = True
            # latched "FA<sig> <x> c<abc>"  (sum)
            fa = re.match(r"^FA(\d+) (-?\d+) c\d\d\d$", nm.strip())
            if fa and not saw_per_combo:
                s = int(fa.group(2)); saw_fa = True
            # latched "FC<sig> <x> c<abc>"  (cout)
            fc = re.match(r"^FC(\d+) (-?\d+) c\d\d\d$", nm.strip())
            if fc and not saw_per_combo:
                m = int(fc.group(2)); saw_fc = True
            if "ERR" in nm:
                break
            # stop once we have both outputs latched (or the per-combo one-shot)
            if saw_per_combo or (saw_fa and saw_fc):
                # let it latch one more cycle to be safe, then stop
                break
        time.sleep(4)
    try:
        c.close()
    except Exception:
        pass
    time.sleep(1)
    kill()

    sum_bit = 1 if s > Y_SIG else (0 if s >= 0 else -1)
    cout_bit = 1 if m > GM_SIG else (0 if m >= 0 else -1)
    return {"combo": combo, "abc": f"{a}{b}{cin}", "s": s, "m": m, "br": br,
            "sum_bit": sum_bit, "cout_bit": cout_bit,
            "exp_sum": EXP_SUM[combo], "exp_cout": EXP_COUT[combo],
            "ok_sum": sum_bit == EXP_SUM[combo], "ok_cout": cout_bit == EXP_COUT[combo],
            "err": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", type=int, required=True)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    r = run_combo(a.combo, a.timeout)
    print(f"\nRESULT combo {r['combo']} (abc={r['abc']}): "
          f"sum_x={r['s']} (>{Y_SIG} => {r.get('sum_bit')}) | "
          f"cout_x={r['m']} (>{GM_SIG} => {r.get('cout_bit')}) | b{r['br']} | "
          f"exp sum={r['exp_sum']} cout={r['exp_cout']} | "
          f"sumOK={r.get('ok_sum')} coutOK={r.get('ok_cout')}")
    clean = r.get("ok_sum") and r.get("ok_cout")
    print(f"CLEAN={clean and r['br']==1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
