"""Single-combo full-adder runner.

Builds and reads ONE (a,b,cin) combo of the facombo GS per fresh sole-process server.
The combo 0..7 is selected by the GS setting `combo`, set per run by writing
[game_scripts.facombo] combo = N into openttd.cfg before launch (the GS reads it via
GSController.GetSetting("combo")). This does NOT compute anything in Python; it relays
the company name the GS sets (the GS encodes RAW reader x), and the operator judges the
output from the raw positions (sum x > Y_SIG=50 => 1; cout x > GM_SIG=40 => 1).

HARNESS RULE: sole process only. Every run hard-kills stray openttd + leftover run_fixed
python FIRST, so a zombie cannot kill the live server.

Usage:
  python tools/run_facombo.py --combo 0 [--timeout 600] [--retries 3] [--map 8]
  python tools/run_facombo.py --all  [--timeout 600] [--retries 3]   # combos 0..7 in turn
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

import run_sc1 as sc1  # configure(), set_cfg(), _wait_port(), OTTD_EXE/DIR, PERSONAL  # noqa: E402
from ottd_admin import AdminClient  # noqa: E402

PERSONAL = sc1.PERSONAL
GS_NAME = "facombo"
GS_DIR = "facombo_gs"

# expected truth tables, judged from raw x (used only to LABEL the readout, never to compute it)
EXP_SUM = [0, 1, 1, 0, 1, 0, 0, 1]   # parity(a,b,cin)
EXP_COUT = [0, 0, 0, 1, 0, 1, 1, 1]  # majority(a,b,cin)
Y_SIG = 50
GM_SIG = 40


def select_gs() -> None:
    """Point openttd.cfg [game_scripts] at facombo only (drop any other entry)."""
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


def set_combo(combo: int) -> None:
    """Write [game_scripts.facombo] combo = N (the GS reads it via GetSetting)."""
    cfg = os.path.join(PERSONAL, "openttd.cfg")
    lines = open(cfg, encoding="utf-8", errors="replace").read().split("\n")
    sec = f"[game_scripts.{GS_NAME}]"
    out, in_sec, wrote_key, saw_sec = [], False, False, False
    for ln in lines:
        s = ln.strip()
        if s.startswith("["):
            if in_sec and not wrote_key:
                out.append(f"combo = {combo}")
                wrote_key = True
            in_sec = (s == sec)
            if in_sec:
                saw_sec = True
            out.append(ln)
            continue
        if in_sec and re.match(r"^combo\s*=", s):
            out.append(f"combo = {combo}")
            wrote_key = True
            continue
        out.append(ln)
    if in_sec and not wrote_key:
        out.append(f"combo = {combo}")
    elif not saw_sec:
        out.append(sec)
        out.append(f"combo = {combo}")
    open(cfg, "w", encoding="utf-8").write("\n".join(out))


def install_gs(combo: int) -> None:
    """Install info.nut + main.nut into the game dir, rewriting the COMBO_SEL source constant so the
    GS builds exactly ONE selected band. (The [game_scripts.facombo] cfg setting is NOT applied to a
    dedicated-server newgame GS here, GetSetting returns the default 0, verified, so the source
    constant is the reliable per-run selector.)"""
    src = os.path.join(REPO, "scenarios", GS_DIR)
    dst = os.path.join(PERSONAL, "game", GS_DIR)
    os.makedirs(dst, exist_ok=True)
    open(os.path.join(dst, "info.nut"), "w", encoding="utf-8").write(
        open(os.path.join(src, "info.nut"), encoding="utf-8").read())
    main = open(os.path.join(src, "main.nut"), encoding="utf-8").read()
    patched, n = re.subn(r"^COMBO_SEL <- \d+;", f"COMBO_SEL <- {combo};", main, count=1,
                         flags=re.MULTILINE)
    if n != 1:
        raise RuntimeError("could not find COMBO_SEL line to rewrite in facombo main.nut")
    open(os.path.join(dst, "main.nut"), "w", encoding="utf-8").write(patched)


def _kill() -> None:
    # sole-process discipline: kill any stray live server AND any leftover runner python.
    subprocess.run(["taskkill", "/F", "/IM", "openttd.exe"], capture_output=True)
    time.sleep(2)


def parse_combo_line(name: str):
    """Return (s, m) raw x from a 'c<abc> s<x> m<x>' company name, or None."""
    m = re.match(r"^c\d\d\d s(-?\d+) m(-?\d+)$", name.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_sum_line(name: str):
    """Return the SUM raw x from a latched 'FA<sig> <x> c<abc>' company name, or None."""
    m = re.match(r"^FA\d+ (-?\d+)( c\d\d\d)?$", name.strip())
    return int(m.group(1)) if m else None


def parse_cout_line(name: str):
    """Return the CARRY raw x from a latched 'FC<sig> <x> c<abc>' company name, or None."""
    m = re.match(r"^FC\d+ (-?\d+)( c\d\d\d)?$", name.strip())
    return int(m.group(1)) if m else None


def run_once(combo: int, timeout: int) -> dict:
    _kill()
    subprocess.Popen([sc1.OTTD_EXE, "-D", "-d", "script=1"], cwd=sc1.OTTD_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not sc1._wait_port():
        print("  admin port did not open")
        return {"name": "", "s": -1, "m": -1, "br": None}
    c = AdminClient()
    c.connect()
    c.rcon("start_ai Idle")

    def company_name() -> str:
        for attempt in range(2):
            try:
                for l in c.rcon("companies"):
                    mm = re.search(r"Company Name: '([^']*)'", l)
                    if mm:
                        return mm.group(1)
                return ""
            except (OSError, Exception):
                try:
                    c.close()
                except Exception:
                    pass
                time.sleep(1)
        return ""

    final, last, t0 = "", "", time.time()
    s, m, br = -1, -1, None
    while time.time() - t0 < timeout:
        nm = company_name()
        if nm and nm != last:
            print(f"    +{int(time.time()-t0)}s '{nm}'", flush=True)
            last = nm
        if nm:
            final = nm
            mb = re.match(r"^FA built1 b(\d)$", nm)
            if mb:
                br = int(mb.group(1))
            pc = parse_combo_line(nm)
            if pc is not None:
                # the combined per-combo readout 'c<abc> s<x> m<x>': both raw x at once.
                s, m = pc
                break
            # the GS also STREAMS the latched 'FA<sig> <x>' (sum) and 'FC<sig> <x>' (cout) lines in
            # turn (each under the ~31-char name limit). Capture whichever the poll catches; once BOTH
            # raw x are seen the readout is complete. The raw x comes ONLY from the GS company name.
            ps = parse_sum_line(nm)
            if ps is not None:
                s = ps
            pm = parse_cout_line(nm)
            if pm is not None:
                m = pm
            if s >= 0 and m >= 0:
                break
            if "ERR" in nm:
                break
        time.sleep(4)
    try:
        c.close()
    except Exception:
        pass
    time.sleep(1)
    _kill()
    return {"name": final, "s": s, "m": m, "br": br}


def judge(combo: int, s: int, m: int):
    sum_bit = 1 if s > Y_SIG else (0 if s >= 0 else -1)
    cout_bit = 1 if m > GM_SIG else (0 if m >= 0 else -1)
    ok_sum = (sum_bit == EXP_SUM[combo])
    ok_cout = (cout_bit == EXP_COUT[combo])
    return sum_bit, cout_bit, ok_sum, ok_cout


def run_combo(combo: int, timeout: int, retries: int) -> dict:
    set_combo(combo)        # cfg subsection (belt-and-suspenders; not relied upon)
    install_gs(combo)       # the reliable selector: rewrite COMBO_SEL in the installed main.nut
    a, b, cin = (combo >> 2) & 1, (combo >> 1) & 1, combo & 1
    best = None
    for attempt in range(1, retries + 1):
        print(f"###### combo {combo} (abc={a}{b}{cin}) attempt {attempt}/{retries} "
              f"{time.strftime('%H:%M:%S')} ######", flush=True)
        r = run_once(combo, timeout)
        s, m, br = r["s"], r["m"], r["br"]
        sum_bit, cout_bit, ok_sum, ok_cout = judge(combo, s, m)
        r.update(sum_bit=sum_bit, cout_bit=cout_bit, ok_sum=ok_sum, ok_cout=ok_cout,
                 combo=combo, a=a, b=b, cin=cin)
        print(f"###### combo {combo} result: name='{r['name']}' s={s}(>{Y_SIG}={sum_bit}) "
              f"m={m}(>{GM_SIG}={cout_bit}) b{br} | exp sum={EXP_SUM[combo]} cout={EXP_COUT[combo]} "
              f"| sumOK={ok_sum} coutOK={ok_cout}", flush=True)
        if best is None or (int(r["ok_sum"]) + int(r["ok_cout"])) > (int(best["ok_sum"]) + int(best["ok_cout"])):
            best = r
        if ok_sum and ok_cout and br == 1:
            break
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--map", type=int, default=8)
    a = ap.parse_args()
    sc1.configure(map_log2=a.map)
    select_gs()

    combos = list(range(8)) if a.all else [a.combo if a.combo is not None else 0]
    results = {}
    for combo in combos:
        results[combo] = run_combo(combo, a.timeout, a.retries)

    print("\n==== TRUTH TABLE (raw x judged externally) ====")
    print("  abc | sum_x sum | cout_x cout | exp_sum exp_cout | br | OK")
    n_clean = 0
    for combo in combos:
        r = results[combo]
        clean = r["ok_sum"] and r["ok_cout"] and r["br"] == 1
        if clean:
            n_clean += 1
        a3 = f"{(combo>>2)&1}{(combo>>1)&1}{combo&1}"
        print(f"  {a3} | {r['s']:>5} {r['sum_bit']:>3} | {r['m']:>6} {r['cout_bit']:>4} | "
              f"{EXP_SUM[combo]:>7} {EXP_COUT[combo]:>8} | b{r['br']} | "
              f"{'CLEAN' if clean else 'sumOK=%d coutOK=%d' % (r['ok_sum'], r['ok_cout'])}")
    print(f"\n  {n_clean}/{len(combos)} combos clean on BOTH outputs with all bridges built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
