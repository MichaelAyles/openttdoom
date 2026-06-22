"""Play the raycaster maze, with the real 1-bit machine output shown alongside.

Run it from your own terminal (so the window attaches to your desktop):

    python golden/play.py

Controls: arrow keys or WASD. Up/W and Down/S walk, Left/A and Right/D turn. Hold
Shift to move faster. Press M to switch what the machine inset shows, R to switch
its resolution. Esc or closing the window quits.

What you are looking at. The big view is a smooth, shaded raycaster (floor, ceiling,
distance shading, a minimap) so the maze is actually navigable. It walks the SAME 16x16
map the machine uses. The small inset is the real workload: the exact 1-bit framebuffer
the train machine computes, rendered for your current view by the proven golden model.

The inset has two honest modes, both pinned bit-identical in test_raycaster.py:

  - ENHANCED (default): render_reference_hi, the gorgeous-within-1-bit target the eventual
    hardware FSM must reproduce. Bayer 4x4 ordered dither of wall brightness by depth,
    dithered floor and ceiling that turn the slabs into a room, 1px black edge seams, a
    vertical wall texture, at 64x32 or 96x48. This is the look the trains are aiming for.
  - PLAIN: render_reference, the flat 1-bit slices the current hand-assembled CHIP-8 ROM
    actually produces today (proven bit-identical to the ROM bytes).

Press M to flip between them and see how much the enhanced renderer buys within one bit.
The big view is just a comfortable lens on the same world; the inset is the honest hardware.

Headless self-test (no window, for CI):

    python golden/play.py --selftest
"""

from __future__ import annotations

import math
import sys

import numpy as np

import raycaster as rc

MAP = rc.MAP
MAP_N = rc.MAP_N
SUB = rc.SUB                      # 16 position-units per cell; axes are 0..255.

# --- movement ---------------------------------------------------------------

MOVE_STEP = 2.2                  # position-units per frame walked.
TURN_STEP = 0.06                 # radians per frame turned.
PAD = 4.0                        # keep this clear of a wall when moving.


def _cell_solid_at(px: float, py: float) -> bool:
    return rc._cell_solid(int(px) // SUB, int(py) // SUB)


def move(px: float, py: float, heading: float, forward: float) -> tuple[float, float]:
    """Walk along heading (radians), sliding on walls, axes clamped to 0..255."""
    dx = math.cos(heading) * MOVE_STEP * forward
    dy = math.sin(heading) * MOVE_STEP * forward
    nx, ny = px, py
    if not _cell_solid_at(px + dx + math.copysign(PAD, dx), py):
        nx = min(254.0, max(1.0, px + dx))
    if not _cell_solid_at(px, py + dy + math.copysign(PAD, dy)):
        ny = min(254.0, max(1.0, py + dy))
    return nx, ny


# --- the comfortable shaded raycaster (Lodev-style DDA) ---------------------

FOV_K = 0.72                     # tan(fov/2); ~72 deg field of view.
CEILING = np.array([28, 30, 44], np.uint8)
FLOOR = np.array([60, 52, 44], np.uint8)


def _cast(posx: float, posy: float, rdx: float, rdy: float) -> tuple[float, int]:
    """DDA on the cell grid. Returns (perpendicular distance, wall side 0/1)."""
    mapx, mapy = int(posx), int(posy)
    ddx = abs(1.0 / rdx) if rdx != 0 else 1e30
    ddy = abs(1.0 / rdy) if rdy != 0 else 1e30
    if rdx < 0:
        stepx, sidex = -1, (posx - mapx) * ddx
    else:
        stepx, sidex = 1, (mapx + 1.0 - posx) * ddx
    if rdy < 0:
        stepy, sidey = -1, (posy - mapy) * ddy
    else:
        stepy, sidey = 1, (mapy + 1.0 - posy) * ddy
    side = 0
    for _ in range(64):
        if sidex < sidey:
            sidex += ddx; mapx += stepx; side = 0
        else:
            sidey += ddy; mapy += stepy; side = 1
        if mapx < 0 or mapy < 0 or mapx >= MAP_N or mapy >= MAP_N:
            break
        if MAP[mapy * MAP_N + mapx] == 1:
            break
    if side == 0:
        perp = (mapx - posx + (1 - stepx) / 2) / (rdx if rdx else 1e-6)
    else:
        perp = (mapy - posy + (1 - stepy) / 2) / (rdy if rdy else 1e-6)
    return max(0.02, perp), side


def render_view(px: float, py: float, heading: float, w: int, h: int) -> np.ndarray:
    """A shaded perspective view of the maze as an (h, w, 3) RGB array."""
    img = np.empty((h, w, 3), np.uint8)
    img[: h // 2] = CEILING
    img[h // 2 :] = FLOOR
    cx, cy = px / SUB, py / SUB
    dirx, diry = math.cos(heading), math.sin(heading)
    planex, planey = -diry * FOV_K, dirx * FOV_K
    half = h // 2
    for x in range(w):
        cam = 2.0 * x / w - 1.0
        perp, side = _cast(cx, cy, dirx + planex * cam, diry + planey * cam)
        col = int(h / perp)
        top = max(0, half - col // 2)
        bot = min(h, half + col // 2)
        shade = 255.0 / (1.0 + perp * perp * 0.10)        # distance fade.
        if side == 1:
            shade *= 0.62                                  # darker y-faces, for corners.
        s = int(max(18, min(245, shade)))
        img[top:bot, x] = (s, s, min(255, int(s * 1.05)))  # faint cool tint.
    return img


def render_minimap(px: float, py: float, heading: float, size: int) -> np.ndarray:
    """A small top-down map with the player and facing, as (size, size, 3) RGB."""
    img = np.full((size, size, 3), 18, np.uint8)
    cell = size / MAP_N
    for cy in range(MAP_N):
        for cx in range(MAP_N):
            if MAP[cy * MAP_N + cx]:
                y0, x0 = int(cy * cell), int(cx * cell)
                img[y0 : y0 + int(cell), x0 : x0 + int(cell)] = (90, 96, 120)
    pxs, pys = px / SUB * cell, py / SUB * cell
    r = max(2, int(cell * 0.28))
    yy, xx = int(pys), int(pxs)
    img[max(0, yy - r) : yy + r, max(0, xx - r) : xx + r] = (255, 210, 40)
    for t in range(int(cell * 1.4)):                       # heading line.
        ex = int(pxs + math.cos(heading) * t)
        ey = int(pys + math.sin(heading) * t)
        if 0 <= ex < size and 0 <= ey < size:
            img[ey, ex] = (255, 120, 40)
    return img


def _heading_index(heading: float) -> int:
    """Snap the continuous heading (radians) to the machine's 32 angle steps."""
    return round(heading / (2 * math.pi) * rc.NUM_ANGLES) % rc.NUM_ANGLES


def chip8_frame(px: float, py: float, heading: float) -> np.ndarray:
    """The PLAIN 1-bit output for this view (proven equal to the CHIP-8 ROM), as the
    raw 32x64 framebuffer. Heading snaps to the ROM's 32 angle steps. This is the flat
    slices the current hand-assembled ROM draws today."""
    idx = _heading_index(heading)
    return rc.render_reference(idx, int(px) & 0xFF, int(py) & 0xFF)


def machine_frame(px: float, py: float, heading: float,
                  enhanced: bool = True, res: str = "hi") -> np.ndarray:
    """The 1-bit machine framebuffer for this view, 0/1 uint8.

    enhanced selects render_reference_hi (the gorgeous-within-1-bit FSM target: Bayer
    dither, dithered floor/ceiling, edge seams, wall texture, 64x32 or 96x48) over the
    plain render_reference flat slices. Both are the proven oracles, pinned in
    test_raycaster.py; this is just a lens switch over the same honest hardware output.
    res ("lo" 64x32 / "hi" 96x48) only applies to the enhanced renderer."""
    idx = _heading_index(heading)
    if enhanced:
        return rc.render_reference_hi(idx, int(px) & 0xFF, int(py) & 0xFF, res=res)
    return rc.render_reference(idx, int(px) & 0xFF, int(py) & 0xFF)


# the enhanced renderer is per-pixel pure Python, so cache the inset and only recompute
# when the snapped view (heading index, integer position) or the mode actually changes.
# the play loop runs at 60fps but the machine output only updates on the 32 angle steps.
_INSET_CACHE: dict = {"key": None, "frame": None}


def _machine_frame_cached(px: float, py: float, heading: float,
                          enhanced: bool, res: str) -> np.ndarray:
    key = (_heading_index(heading), int(px) & 0xFF, int(py) & 0xFF, enhanced, res)
    if _INSET_CACHE["key"] != key:
        _INSET_CACHE["key"] = key
        _INSET_CACHE["frame"] = machine_frame(px, py, heading, enhanced, res)
    return _INSET_CACHE["frame"]


# --- compositing ------------------------------------------------------------

def _blit_panel(img: np.ndarray, disp: np.ndarray, w: int, h: int) -> tuple[int, int, int, int]:
    """Blit a 0/1 framebuffer as the scaled-up machine inset, bottom-left, on a dark
    backing. Returns the panel rectangle (x0, y0, pw, ph) for caption placement."""
    fh, fw = disp.shape
    # scale to roughly a quarter of the window width regardless of inset resolution, so
    # the 64x32 and 96x48 modes occupy the same screen real estate.
    scale = max(2, (w // 4) // fw)
    pw, ph = fw * scale, fh * scale
    panel = (disp.astype(np.uint8) * 255)[:, :, None].repeat(3, 2)
    panel = np.kron(panel, np.ones((scale, scale, 1), np.uint8))
    y0, x0 = h - 6 - ph, 6
    img[y0 - 12 : y0 + ph + 2, x0 - 2 : x0 + pw + 2] = (10, 10, 14)   # backing.
    img[y0 : y0 + ph, x0 : x0 + pw] = panel
    return x0, y0, pw, ph


def compose(px: float, py: float, heading: float, w: int, h: int,
            enhanced: bool = True, res: str = "hi") -> np.ndarray:
    """The full frame: shaded view + minimap + the real machine inset. (h, w, 3).

    enhanced/res pick what the inset shows (see machine_frame). The default is the
    enhanced 96x48 output, so what the player reads as the real machine output is the
    gorgeous-within-1-bit version the trains are aiming for."""
    img = render_view(px, py, heading, w, h)

    mm = max(96, w // 5)
    mini = render_minimap(px, py, heading, mm)
    img[6 : 6 + mm, w - 6 - mm : w - 6] = mini

    disp = _machine_frame_cached(px, py, heading, enhanced, res)
    _blit_panel(img, disp, w, h)
    return img


# --- interactive front end --------------------------------------------------

def play(w: int = 640, h: int = 400, fps: int = 60) -> None:
    try:
        import pygame
    except Exception as exc:  # pragma: no cover
        print(f"pygame unavailable: {exc}\nInstall it with: python -m pip install pygame")
        return
    pygame.init()
    win = pygame.display.set_mode((w, h))
    pygame.display.set_caption("openttdoom raycaster")
    font = pygame.font.SysFont("consolas", 14)
    clock = pygame.time.Clock()

    px, py = float(rc.PLAYER_X), float(rc.PLAYER_Y)
    heading = 0.0
    enhanced = True                 # inset shows the enhanced 1-bit target by default.
    res = "hi"                       # 96x48; press R for 64x32 ("lo").
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_m:           # flip enhanced / plain machine.
                    enhanced = not enhanced
                elif event.key == pygame.K_r:           # flip inset resolution.
                    res = "lo" if res == "hi" else "hi"
        keys = pygame.key.get_pressed()
        boost = 2.0 if (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) else 1.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            heading -= TURN_STEP * boost
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            heading += TURN_STEP * boost
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            px, py = move(px, py, heading, +1.0 * boost)
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            px, py = move(px, py, heading, -1.0 * boost)

        frame = compose(px, py, heading, w, h, enhanced=enhanced, res=res)
        # numpy is (h, w, 3); pygame surfarray wants (w, h, 3).
        pygame.surfarray.blit_array(win, np.transpose(frame, (1, 0, 2)))
        if enhanced:
            dims = "96x48" if res == "hi" else "64x32"
            label = f"MACHINE 1-bit {dims} enhanced  (what the trains aim for)"
        else:
            label = "MACHINE 1-bit 64x32 plain  (what the ROM draws today)"
        cap = font.render(label, True, (160, 200, 160))
        win.blit(cap, (8, h - 22))
        hud = font.render(
            "WASD/arrows move - Shift faster - M mode - R res - Esc quit",
            True, (180, 180, 180))
        win.blit(hud, (8, 6))
        pygame.display.flip()
        clock.tick(fps)
    pygame.quit()


# --- headless self-test -----------------------------------------------------

def selftest() -> int:
    f0 = compose(rc.PLAYER_X, rc.PLAYER_Y, 0.0, 320, 200)
    assert f0.shape == (200, 320, 3), f0.shape
    assert f0.std() > 5, "frame looks flat / blank"
    f1 = compose(rc.PLAYER_X, rc.PLAYER_Y, 1.2, 320, 200)
    assert not np.array_equal(f0, f1), "turning did not change the view"
    px, py, hd = float(rc.PLAYER_X), float(rc.PLAYER_Y), 0.0
    for _ in range(10):
        px, py = move(px, py, hd, +1.0)
        assert not _cell_solid_at(px, py), f"walked into a wall at ({px},{py})"

    # the inset is the honest hardware output in BOTH modes. confirm each mode the
    # player can see is bit-identical to its proven oracle (test_raycaster.py pins both).
    idx = _heading_index(0.0)
    # plain mode == render_reference (the flat slices the CHIP-8 ROM draws today).
    assert np.array_equal(
        machine_frame(rc.PLAYER_X, rc.PLAYER_Y, 0.0, enhanced=False),
        rc.render_reference(idx, rc.PLAYER_X, rc.PLAYER_Y)), "plain inset != oracle"
    # the legacy chip8_frame helper still returns the plain oracle frame.
    assert np.array_equal(chip8_frame(rc.PLAYER_X, rc.PLAYER_Y, 0.0),
                          rc.render_reference(idx, rc.PLAYER_X, rc.PLAYER_Y))
    # enhanced mode == render_reference_hi, the gorgeous-within-1-bit target, at both
    # resolutions. this is what the player sees as the real machine output by default.
    for res in ("lo", "hi"):
        got = machine_frame(rc.PLAYER_X, rc.PLAYER_Y, 0.0, enhanced=True, res=res)
        want = rc.render_reference_hi(idx, rc.PLAYER_X, rc.PLAYER_Y, res=res)
        assert np.array_equal(got, want), f"enhanced inset ({res}) != oracle"
        assert set(np.unique(got)).issubset({0, 1}), "enhanced inset is not 1-bit"
    # the default compose() actually shows the enhanced inset: it must differ from a
    # compose() forced to the plain inset, otherwise the wiring did not take.
    enh = compose(rc.PLAYER_X, rc.PLAYER_Y, 0.0, 320, 200, enhanced=True, res="hi")
    pln = compose(rc.PLAYER_X, rc.PLAYER_Y, 0.0, 320, 200, enhanced=False)
    assert not np.array_equal(enh, pln), "enhanced and plain insets composed identically"

    print("selftest OK: shaded view renders, turns, walks; "
          "enhanced inset == render_reference_hi (lo+hi) and plain inset == render_reference.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    play()
