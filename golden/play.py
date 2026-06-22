"""Play the raycaster interactively on the golden CHIP-8 interpreter.

Run it:

    python golden/play.py

Controls: arrow keys or WASD. Up/W and Down/S walk forward and back, Left/A and
Right/D turn. Esc or closing the window quits.

What is and is not "the machine" here. EVERY frame you see is rendered by the real
raycaster CHIP-8 ROM (golden/raycaster.py build_rom) executing for real in the golden
chip8.Chip8 interpreter, the exact bytes the train machine would run. The only thing
that lives in Python is the camera loop: reading the keys and walking the player
position around the map (with collision against the same map the ROM uses). The current
raycaster ROM bakes the camera in as immediates and takes no input, so to make it
playable we rebuild and re-run the ROM for the new viewpoint each time you move. A fully
self-contained interactive ROM (movement done inside CHIP-8) is the natural follow-on and
is the version that would eventually run on the trains.

There is also a headless self-test (no window) so the render path can be checked in CI:

    python golden/play.py --selftest
"""

from __future__ import annotations

import math
import sys

import numpy as np

from chip8 import SCREEN_H, SCREEN_W
import raycaster as rc


# --- camera, movement and the per-frame render ------------------------------

# movement tuning, positions are in 1/16-of-a-cell units (0..255 per axis).
MOVE_STEP = 3          # units walked per frame when a move key is held.
TURN_STEP = 1          # angle units turned per frame when a turn key is held.
COLLIDE_PAD = 3        # keep this far (units) clear of a wall when moving.


def _solid_at(px: float, py: float) -> bool:
    """True if the cell containing (px, py) is a wall (or off the map)."""
    return rc._cell_solid(int(px) >> 4, int(py) >> 4)


def try_move(px: float, py: float, heading: int, forward: int) -> tuple[float, float]:
    """Walk the player along its heading by forward (+1 ahead, -1 back), sliding
    along walls: each axis moves only if its own target cell is clear. Returns the
    new (px, py)."""
    ang = (heading / rc.NUM_ANGLES) * 2.0 * math.pi
    dx = math.cos(ang) * MOVE_STEP * forward
    dy = math.sin(ang) * MOVE_STEP * forward
    nx, ny = px, py
    # probe a little past the move so we stop before entering the wall cell.
    if not _solid_at(px + dx + math.copysign(COLLIDE_PAD, dx), py):
        nx = min(255.0, max(0.0, px + dx))
    if not _solid_at(px, py + dy + math.copysign(COLLIDE_PAD, dy)):
        ny = min(255.0, max(0.0, py + dy))
    return nx, ny


def render(heading: int, px: int, py: int) -> np.ndarray:
    """The real raycaster ROM, assembled and executed in the golden interpreter for
    this viewpoint. Returns the 32x64 framebuffer (0/1)."""
    machine = rc.run_rom_bytes(rc.build_rom(heading & (rc.NUM_ANGLES - 1),
                                            int(px) & 0xFF, int(py) & 0xFF))
    return machine.display


# --- interactive pygame front end -------------------------------------------

def play(scale: int = 12, fps: int = 20) -> None:
    try:
        import pygame
    except Exception as exc:  # pragma: no cover - depends on the host
        print(f"pygame unavailable, cannot open the player: {exc}")
        print("Install it with:  python -m pip install pygame")
        return

    pygame.init()
    win = pygame.display.set_mode((SCREEN_W * scale, SCREEN_H * scale))
    pygame.display.set_caption("openttdoom raycaster (CHIP-8)")
    clock = pygame.time.Clock()

    px, py = float(rc.PLAYER_X), float(rc.PLAYER_Y)
    heading = 0
    last_key = None        # (heading, int(px), int(py)) of the last rendered frame.
    surf = None

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            heading = (heading - TURN_STEP) % rc.NUM_ANGLES
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            heading = (heading + TURN_STEP) % rc.NUM_ANGLES
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            px, py = try_move(px, py, heading, +1)
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            px, py = try_move(px, py, heading, -1)

        # only re-run the ROM when the viewpoint actually changed.
        key = (heading, int(px), int(py))
        if key != last_key:
            disp = render(heading, int(px), int(py))
            rgb = np.stack([disp.T.astype(np.uint8) * 230] * 3, axis=-1)
            rgb[..., 2] = disp.T.astype(np.uint8) * 255      # a faint blue tint.
            small = pygame.surfarray.make_surface(rgb)
            surf = pygame.transform.scale(small, (SCREEN_W * scale, SCREEN_H * scale))
            last_key = key
            pygame.display.set_caption(
                f"openttdoom raycaster (CHIP-8)  pos ({int(px)},{int(py)}) "
                f"heading {heading}/{rc.NUM_ANGLES}  [WASD/arrows move, Esc quit]")

        if surf is not None:
            win.blit(surf, (0, 0))
            pygame.display.flip()
        clock.tick(fps)

    pygame.quit()


# --- headless self-test (no window) -----------------------------------------

def selftest() -> int:
    """Exercise the render + movement path without a window. Confirms the real ROM
    renders a non-empty frame, that different headings differ, and that walking
    forward changes the view. Returns a process exit code."""
    base = render(0, int(rc.PLAYER_X), int(rc.PLAYER_Y))
    assert base.shape == (SCREEN_H, SCREEN_W), base.shape
    assert base.sum() > 0, "frame is empty, the ROM drew nothing"

    spun = render(8, int(rc.PLAYER_X), int(rc.PLAYER_Y))
    assert not np.array_equal(base, spun), "turning did not change the view"

    # walk forward a few steps from the start, the frame should evolve and we must
    # never end up standing inside a wall.
    px, py, heading = float(rc.PLAYER_X), float(rc.PLAYER_Y), 0
    seen = {tuple(base.flatten())}
    moved = False
    for _ in range(12):
        px, py = try_move(px, py, heading, +1)
        assert not _solid_at(px, py), f"walked into a wall at ({px},{py})"
        frame = render(heading, int(px), int(py))
        if tuple(frame.flatten()) not in seen:
            moved = True
        seen.add(tuple(frame.flatten()))
    assert moved, "walking forward never changed the frame"

    print("selftest OK: real CHIP-8 raycaster renders, turns and walks.")
    print(f"  base frame lit pixels: {int(base.sum())} / {SCREEN_H * SCREEN_W}")
    print(f"  distinct frames over a 12-step walk: {len(seen)}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    play()
