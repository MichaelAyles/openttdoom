"""Render the showcase artifacts for the gorgeous 1-bit raycaster.

Everything here is driven by the ENHANCED 1-bit oracle, raycaster.render_reference_hi
(Bayer 4x4 dither, 1px black edge seams, depth-discontinuity seams, dithered floor and
ceiling, vertical wall texture, both 64x32 and 96x48). That oracle is the frozen target
the eventual hardware FSM must reproduce bit for bit, pinned by sha256 in test_raycaster.py.
Nothing in this file changes the oracle or any contract, it only renders it.

Two deliverables, written to out_screens/:

  1. a set of STILL FRAMES at several headings and positions, at 96x48 and 64x32, each the
     enhanced 1-bit machine output, scaled up cleanly (nearest-neighbour, integer scale) so
     the dither pattern stays crisp.

  2. an auto-piloted WALKTHROUGH GIF, raycaster_hi_walkthrough.gif: a camera that tours the
     maze (it walks real open corridors using the same collision logic play.py uses, and
     turns to look down them), every frame the enhanced 1-bit render, scaled up to be
     eyeballable at a comfortable frame rate.

Determinism: render_reference_hi is a pure function of (heading, px, py, res). The autopilot
path is a fixed waypoint list, so the whole GIF is reproducible byte for byte. We snap the
camera heading to the oracle's NUM_ANGLES angle steps before rendering each frame (the 1-bit
machine only has those angle steps), so what the GIF shows is exactly a machine frame.

Run:  python golden/showcase_hi.py
"""

from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image

import raycaster as rc

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_DIR = os.path.join(REPO, "out_screens")

SUB = rc.SUB                       # position units per cell; each axis is 0..255.
MAP = rc.MAP
MAP_N = rc.MAP_N


# --- 1-bit frame -> crisp upscaled PNG/array --------------------------------

def upscale(frame: np.ndarray, scale: int) -> np.ndarray:
    """Integer nearest-neighbour upscale of a 0/1 frame to an 8-bit grayscale array
    (lit = 255). Nearest-neighbour keeps every dither dot a hard square, which is the
    honest way to show a 1-bit panel: no interpolation, no invented grey."""
    buf = (frame.astype(np.uint8) * 255)
    return np.kron(buf, np.ones((scale, scale), dtype=np.uint8))


def save_frame_png(frame: np.ndarray, path: str, scale: int) -> None:
    """Save a 1-bit oracle frame as a true black/white PNG, integer-scaled."""
    img = Image.fromarray(upscale(frame, scale), mode="L").convert("1")
    img.save(path)


# --- autopilot: glide through real open corridors ---------------------------
# Reuse play.py's movement model (slide on walls, axes clamped to 0..255) so the
# camera only ever travels through genuinely open space, then snap its heading to
# the oracle's angle grid before rendering. The path is a fixed waypoint tour, so
# the whole walkthrough is deterministic.

MOVE_STEP = 2.6                    # position-units advanced per tick toward a waypoint.
TURN_RATE = 0.13                   # radians per tick the heading slews toward target.
PAD = 5.0                          # keep this clear of a wall when moving.
ARRIVE = 6.0                       # within this many units, a waypoint is reached.


def _cell_solid_at(px: float, py: float) -> bool:
    return rc._cell_solid(int(px) // SUB, int(py) // SUB)


def _try_move(px: float, py: float, heading: float, speed: float) -> tuple[float, float]:
    """Walk along heading, sliding on walls (axis-independent), clamped to the map."""
    dx = math.cos(heading) * speed
    dy = math.sin(heading) * speed
    nx, ny = px, py
    if not _cell_solid_at(px + dx + math.copysign(PAD, dx), py):
        nx = min(254.0, max(1.0, px + dx))
    if not _cell_solid_at(px, py + dy + math.copysign(PAD, dy)):
        ny = min(254.0, max(1.0, py + dy))
    return nx, ny


def cell_center(cx: int, cy: int) -> tuple[float, float]:
    return cx * SUB + SUB / 2.0, cy * SUB + SUB / 2.0


# A waypoint tour of the maze. Each entry is an open cell; consecutive cells are
# 4-neighbour adjacent through open space, so the straight-line glide between them
# never clips a wall. Verified open + adjacency by _validate_tour() below. The tour
# leaves the start room, runs the long top corridor, dips into the interior rooms,
# crosses the lower hall, and returns, so the GIF reveals walls at many depths.
TOUR_CELLS = [
    (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1),
    (9, 1), (10, 1), (11, 1), (12, 1), (13, 1), (14, 1),
    (14, 2), (14, 3), (14, 4), (14, 5),
    (13, 5), (13, 6), (13, 7),
    (14, 7), (14, 8), (14, 9),
    (13, 9), (12, 9), (11, 9),
    (11, 10), (11, 11),
    (12, 11), (13, 11), (14, 11),
    (14, 12), (14, 13), (14, 14),
    (13, 14), (12, 14), (11, 14), (10, 14), (9, 14), (8, 14),
    (7, 14), (6, 14), (5, 14), (4, 14), (3, 14), (2, 14), (1, 14),
    (1, 13), (1, 12), (1, 11),
    (2, 11), (3, 11), (4, 11),
    (4, 10), (4, 9),
    (5, 9), (6, 9), (7, 9), (8, 9), (9, 9),
    (9, 8), (9, 7), (9, 6), (9, 5), (9, 4),
    (8, 4), (7, 4), (6, 4), (5, 4), (4, 4), (3, 4),
    (3, 5), (3, 6), (3, 7),
    (2, 7), (1, 7), (1, 6), (1, 5), (1, 4), (1, 3), (1, 2), (1, 1),
]


def _validate_tour(cells: list[tuple[int, int]]) -> None:
    """Fail loudly if any tour cell is a wall or any hop is not 4-neighbour adjacent
    through open space. Keeps the autopilot honest: the camera never clips a wall."""
    for cx, cy in cells:
        assert MAP[cy * MAP_N + cx] == 0, f"tour cell ({cx},{cy}) is a wall"
    for (ax, ay), (bx, by) in zip(cells, cells[1:]):
        man = abs(ax - bx) + abs(ay - by)
        assert man == 1, f"non-adjacent hop ({ax},{ay})->({bx},{by}) (manhattan {man})"


def _ang_to(px: float, py: float, tx: float, ty: float) -> float:
    return math.atan2(ty - py, tx - px)


def _slew(cur: float, target: float, rate: float) -> float:
    """Move angle cur toward target by at most rate, taking the short way round."""
    d = (target - cur + math.pi) % (2 * math.pi) - math.pi
    if abs(d) <= rate:
        return target
    return cur + math.copysign(rate, d)


def autopilot_frames(res: str, max_frames: int = 100000):
    """Yield (px, py, snapped_heading_index) for the walkthrough. The camera turns
    toward the next waypoint, walks to it sliding on walls, and continues. Heading is
    snapped to the oracle's NUM_ANGLES grid for each yielded frame so every frame is a
    real machine frame. Deterministic: fixed path, fixed steps."""
    _validate_tour(TOUR_CELLS)
    px, py = cell_center(*TOUR_CELLS[0])
    heading = 0.0
    yielded = 0
    for wi in range(1, len(TOUR_CELLS)):
        tx, ty = cell_center(*TOUR_CELLS[wi])
        # turn-then-walk, with a hard step cap per leg so a blocked glide cannot spin.
        for _ in range(400):
            target = _ang_to(px, py, tx, ty)
            heading = _slew(heading, target, TURN_RATE)
            # only advance once roughly facing the waypoint, so turns read as turns.
            facing = abs((target - heading + math.pi) % (2 * math.pi) - math.pi)
            if facing < 0.25:
                px, py = _try_move(px, py, heading, MOVE_STEP)
            idx = round(heading / (2 * math.pi) * rc.NUM_ANGLES) % rc.NUM_ANGLES
            yield (px, py, idx)
            yielded += 1
            if yielded >= max_frames:
                return
            if math.hypot(tx - px, ty - py) <= ARRIVE:
                break


# --- deliverable 1: still frames --------------------------------------------
# A spread of viewpoints: several headings from the start room, plus a few from
# deeper interior cells, at BOTH resolutions. Each is the enhanced 1-bit oracle.

STILL_VIEWS = [
    # (label, cell_x, cell_y, heading_index)
    ("start_corridor", 1, 1, 0),     # looking down the long top corridor.
    ("start_angle", 1, 1, 6),        # oblique, a near corner plus a far wall.
    ("start_room", 1, 1, 12),        # back into the open corner room, depth galore.
    ("hall_deep", 7, 1, 16),         # mid top corridor, walls both sides receding.
    ("interior_room", 9, 9, 20),     # an interior junction, mixed depths.
    ("interior_turn", 5, 9, 4),      # a corridor mouth, sharp depth seam.
    ("lower_hall", 8, 14, 24),       # the long lower hall.
    ("left_spine", 1, 7, 0),         # the left spine corridor.
]

STILL_SCALE = {"lo": 8, "hi": 6}   # lo 64x32->512x256, hi 96x48->576x288: comparable size.


def render_stills() -> list[tuple[str, str, int]]:
    """Render every STILL_VIEW at both resolutions to out_screens/. Returns a list of
    (path, sha256-prefix, lit) for the report."""
    import hashlib

    results = []
    for res in ("hi", "lo"):
        for label, cx, cy, hd in STILL_VIEWS:
            px, py = cell_center(cx, cy)
            frame = rc.render_reference_hi(hd, int(px) & 0xFF, int(py) & 0xFF, res=res)
            name = f"ray_hi_still_{res}_{label}_h{hd:02d}.png"
            path = os.path.join(OUT_DIR, name)
            save_frame_png(frame, path, STILL_SCALE[res])
            digest = hashlib.sha256(frame.tobytes()).hexdigest()[:12]
            results.append((path, digest, int(frame.sum())))
    return results


# --- deliverable 2: the walkthrough GIF -------------------------------------

GIF_RES = "hi"                     # the high-res panel for the headline animation.
GIF_SCALE = 7                      # 96x48 -> 672x336, crisp dither.
GIF_FRAME_MS = 80                  # ~12.5 fps: smooth but lets the eye read the dither.


def render_walkthrough() -> tuple[str, int, int]:
    """Render the auto-piloted walkthrough GIF. Returns (path, total_frames,
    distinct_frames). Each GIF frame is the enhanced 1-bit oracle for the autopilot's
    snapped heading and position, upscaled nearest-neighbour. Consecutive identical
    machine frames (the camera mid-glide between two angle steps) are collapsed to one,
    so the GIF stays tight and every frame shown is a visibly different machine frame."""
    import hashlib

    frames_pil = []
    seen = {}
    distinct = 0
    total = 0
    last_key = None
    for px, py, idx in autopilot_frames(GIF_RES):
        frame = rc.render_reference_hi(idx, int(px) & 0xFF, int(py) & 0xFF, res=GIF_RES)
        key = hashlib.sha256(frame.tobytes()).hexdigest()
        if key == last_key:
            continue                # identical to the previous frame, drop it.
        last_key = key
        if key not in seen:
            seen[key] = True
            distinct += 1
        img = Image.fromarray(upscale(frame, GIF_SCALE), mode="L").convert("L")
        frames_pil.append(img)
        total += 1

    path = os.path.join(OUT_DIR, "raycaster_hi_walkthrough.gif")
    frames_pil[0].save(
        path,
        save_all=True,
        append_images=frames_pil[1:],
        duration=GIF_FRAME_MS,
        loop=0,
        optimize=True,
    )
    return path, total, distinct


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=== still frames (enhanced 1-bit oracle) ===")
    stills = render_stills()
    for path, digest, lit in stills:
        size = os.path.getsize(path)
        print(f"  {os.path.basename(path):44s} lit {lit:4d}  sha {digest}  {size:6d} B")

    print("\n=== walkthrough GIF ===")
    gif_path, total, distinct = render_walkthrough()
    gif_size = os.path.getsize(gif_path)
    print(f"  {os.path.basename(gif_path)}")
    print(f"  frames: {total} total, {distinct} distinct  size {gif_size} B")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
