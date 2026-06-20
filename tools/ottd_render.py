"""Render an openttdoom design as a real OpenTTD map and screenshot it, headless.

This is the recipe that actually works on the Windows prebuilt binary, where there is no
console output and the GUI cannot be driven directly. It uses OpenTTD's admin TCP port for
control and observability, and these hard-won facts:

  - The admin port (3977) only opens if an admin password is set AND
    allow_insecure_admin_login is true. A wiped password silently disables it.
  - A GameScript runs as a deity and cannot build rail; it needs a company. A dedicated
    server has none, so we create one with the RCON command `start_ai` (the built-in dummy
    AI founds a company even with no AI installed), and the GS waits for it (see main.nut).
  - Construction costs money; the full design can exceed the default loan, so we set a huge
    max_loan and the GS maxes its loan before building (see main.nut).
  - A GameScript name with a SPACE does not round-trip through the config, so the script is
    registered as "openttdoombuilder" (no space).
  - Building needs flat, water-free, clear land: terrain_type=0, no rivers, no water borders,
    no towns, no industries. Building does NOT need graphics, so it runs under the dedicated
    server (-D). Rendering DOES need graphics, so the screenshot is taken from a GUI run that
    loads the saved game (the design is already built, so game_start.scr captures it).

Pipeline: configure -> install scenario_data.nut -> dedicated build (RCON start_ai, poll the
company money until it stops dropping, RCON save) -> GUI load + `screenshot minimap`.

CLI:
  python tools/ottd_render.py <netlist.json> [--out out.png] [--map 10] [--timeout 600]

Requires: tools/ottd_admin.py, the openttdoom toolchain (synth/place_and_route), and the
GameScript installed in the OpenTTD game/ dir (this script installs the scenario data table).
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

OTTD_DIR = os.path.join(REPO, "vendor", "openttd", "openttd-15.3-windows-win64")
OTTD_EXE = os.path.join(OTTD_DIR, "openttd.exe")
PERSONAL = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "OpenTTD")
if not os.path.isdir(PERSONAL):
    PERSONAL = os.path.join(os.path.expanduser("~"), "Documents", "OpenTTD")


# --- tiny ini editor (set key=value within a [section]) ---------------------------

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


def configure(map_log2: int = 10, admin_pw: str = "ottdoom") -> None:
    """Set up the OpenTTD config for headless build + clean render."""
    cfg = os.path.join(PERSONAL, "openttd.cfg")
    sec = os.path.join(PERSONAL, "secrets.cfg")
    set_cfg(sec, "network", "admin_password", admin_pw)
    set_cfg(cfg, "network", "allow_insecure_admin_login", "true")
    set_cfg(cfg, "network", "server_admin_port", "3977")
    set_cfg(cfg, "game_scripts", "openttdoombuilder", "")     # select our GS
    set_cfg(cfg, "difficulty", "terrain_type", "0")           # very flat
    set_cfg(cfg, "difficulty", "number_towns", "0")
    set_cfg(cfg, "difficulty", "industry_density", "0")
    set_cfg(cfg, "difficulty", "max_loan", "2000000000")
    set_cfg(cfg, "game_creation", "amount_of_rivers", "0")
    set_cfg(cfg, "game_creation", "water_borders", "0")
    set_cfg(cfg, "game_creation", "map_x", str(map_log2))


def install_scenario(nut_text: str) -> None:
    p = os.path.join(PERSONAL, "game", "openttdoom_gs", "scenario_data.nut")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(nut_text)


def _kill() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "openttd.exe"],
                   capture_output=True)
    time.sleep(2)


def _wait_port(port: int = 3977, secs: int = 20) -> bool:
    for _ in range(secs):
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            return True
        except OSError:
            time.sleep(1)
    return False


def build(save_name: str, timeout: int = 600) -> bool:
    """Run the dedicated server, create a company, let the GS build, then RCON-save."""
    _kill()
    subprocess.Popen([OTTD_EXE, "-D", "-d", "script=1"],
                     cwd=OTTD_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait_port():
        print("admin port did not open (check admin_password)")
        return False
    c = AdminClient()
    c.connect()
    c.rcon("start_ai")     # found a company for the deity GS to build as

    def money():
        for l in c.rcon("companies"):
            m = re.search(r"Money: (\d+)", l)
            if m:
                return int(m.group(1))
        return None

    prev, stable, t0 = None, 0, time.time()
    while time.time() - t0 < timeout:
        time.sleep(10)
        mv = money()
        print(f"  build t={int(time.time()-t0)}s money={mv}", flush=True)
        if mv is not None and mv == prev:
            stable += 1
            if stable >= 3 and time.time() - t0 > 30:
                print("  build complete (spend stabilised)")
                break
        else:
            stable = 0
        prev = mv
    for l in c.rcon(f"save {save_name}"):
        print("  ", l)
    c.close()
    time.sleep(2)
    _kill()
    return os.path.isfile(os.path.join(PERSONAL, "save", f"{save_name}.sav"))


def screenshot(save_name: str, kind: str = "minimap", shot_name: str = "render") -> str:
    """Load the saved game in a GUI run and screenshot it. Returns the PNG path."""
    _kill()
    gs = os.path.join(OTTD_DIR, "scripts", "game_start.scr")
    open(gs, "w").write(f"screenshot {kind} {shot_name}\n")
    out = os.path.join(PERSONAL, "screenshot", f"{shot_name}.png")
    if os.path.isfile(out):
        os.remove(out)
    sav = os.path.join(PERSONAL, "save", f"{save_name}.sav")
    subprocess.Popen([OTTD_EXE, "-g", sav, "-snull", "-mnull"],
                     cwd=OTTD_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(12)
    _kill()
    return out if os.path.isfile(out) else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist", help="gate-level netlist JSON (NOR-lowered)")
    ap.add_argument("--out", default=os.path.join(REPO, "out_screens", "render.png"))
    ap.add_argument("--map", type=int, default=10, help="map size as log2 (10 = 1024)")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    from netlist import Netlist
    from emit import build_scenario
    nl = Netlist.load(a.netlist)
    sc = build_scenario(nl)
    sc = sc[0] if isinstance(sc, tuple) else sc

    configure(map_log2=a.map)
    install_scenario(sc.to_nut())
    name = os.path.splitext(os.path.basename(a.netlist))[0]
    print(f"building {name} in OpenTTD ...")
    if not build(name, timeout=a.timeout):
        print("build/save failed")
        return 1
    png = screenshot(name, "minimap", name)
    if not png:
        print("screenshot failed")
        return 1
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    import shutil
    shutil.copy(png, a.out)
    print(f"rendered -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
