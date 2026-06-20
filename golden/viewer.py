"""Framebuffer viewer for the golden CHIP-8 model.

Headless first. The two functions a test or a human actually needs are:

  run_rom(path, cycles, **quirks) -> Chip8
      load a ROM, run it for a number of instructions with timer ticks paced at
      the usual ratio, and hand back the machine so you can inspect the display.

  save_png(chip8, path)
      render the 64x32 display buffer to a 1-bit black/white PNG, scaled up so a
      human can actually see it.

There is an OPTIONAL pygame live viewer at the bottom, guarded by try/except. This
environment has no display, so it is never required and never imported at module
load time. numpy and pillow are the only hard dependencies.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from chip8 import Chip8, SCREEN_W, SCREEN_H

# the VIP ran roughly 8 to 15 instructions per 60Hz frame. we tick the timers
# once every CYCLES_PER_TICK instructions so delay/sound timers and any
# display-wait pacing behave sanely. tests that need exact timer counts drive
# step()/tick_timers() directly instead.
CYCLES_PER_TICK = 10

# upscale factor for saved PNGs, so 64x32 becomes something eyeballable.
DEFAULT_SCALE = 8


def run_rom(path: str, cycles: int, *, ticks: bool = True, **quirks) -> Chip8:
    """Load and run a ROM file, returning the machine.

    cycles is the number of instructions to execute. If ticks is true we
    decrement the 60Hz timers every CYCLES_PER_TICK instructions, which is what a
    real machine would do. Extra keyword args are forwarded to Chip8 as quirk
    flags (e.g. vf_reset=False, seed=123).
    """
    machine = Chip8(**quirks)
    with open(path, "rb") as f:
        machine.load_rom(f.read())

    for i in range(cycles):
        if machine.halted:
            break
        machine.step()
        if ticks and (i + 1) % CYCLES_PER_TICK == 0:
            machine.tick_timers()

    return machine


def to_image(chip8: Chip8, scale: int = DEFAULT_SCALE) -> Image.Image:
    """Build a scaled 1-bit PIL image from the display buffer. On pixels are
    white (255), off pixels are black (0)."""
    # display is uint8 of 0/1, map to 0/255.
    buf = (chip8.display * 255).astype(np.uint8)
    img = Image.fromarray(buf, mode="L")
    if scale != 1:
        img = img.resize((SCREEN_W * scale, SCREEN_H * scale), Image.NEAREST)
    # convert to a true 1-bit image so the PNG is genuinely black/white.
    return img.convert("1")


def save_png(chip8: Chip8, path: str, scale: int = DEFAULT_SCALE) -> None:
    """Render the display buffer to a 1-bit PNG at the given path."""
    to_image(chip8, scale).save(path)


def display_hash(chip8: Chip8) -> str:
    """A stable hex digest of the display buffer, handy for determinism checks."""
    import hashlib

    return hashlib.sha256(chip8.display.tobytes()).hexdigest()


# --- optional live viewer ---------------------------------------------------

def live(path: str, *, scale: int = DEFAULT_SCALE, ips: int = 700, **quirks):
    """Run a ROM in a pygame window with the standard CHIP-8 keypad mapping.

    This is best effort. It needs a display, which this build environment does
    not have, so it is guarded: if pygame cannot open a window the function
    prints why and returns instead of crashing. Not used by the tests.
    """
    try:
        import pygame
    except Exception as exc:  # pragma: no cover - optional path.
        print(f"pygame unavailable, live viewer disabled: {exc}")
        return

    # COSMAC VIP keypad to PC keyboard layout.
    keymap = {
        pygame.K_1: 0x1, pygame.K_2: 0x2, pygame.K_3: 0x3, pygame.K_4: 0xC,
        pygame.K_q: 0x4, pygame.K_w: 0x5, pygame.K_e: 0x6, pygame.K_r: 0xD,
        pygame.K_a: 0x7, pygame.K_s: 0x8, pygame.K_d: 0x9, pygame.K_f: 0xE,
        pygame.K_z: 0xA, pygame.K_x: 0x0, pygame.K_c: 0xB, pygame.K_v: 0xF,
    }

    try:
        pygame.init()
        screen = pygame.display.set_mode((SCREEN_W * scale, SCREEN_H * scale))
    except Exception as exc:  # pragma: no cover - optional path.
        print(f"no display available, live viewer disabled: {exc}")
        return

    machine = Chip8(**quirks)
    with open(path, "rb") as f:
        machine.load_rom(f.read())

    pygame.display.set_caption("openttdoom golden CHIP-8")
    clock = pygame.time.Clock()
    cycles_per_frame = max(1, ips // 60)
    running = True

    while running:  # pragma: no cover - interactive loop.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
                k = keymap.get(event.key)
                if k is not None:
                    if event.type == pygame.KEYDOWN:
                        machine.key_down(k)
                    else:
                        machine.key_up(k)

        for _ in range(cycles_per_frame):
            machine.step()
        machine.tick_timers()

        surf = pygame.surfarray.make_surface(
            np.repeat(np.repeat((machine.display.T * 255), scale, 0), scale, 1)
        )
        screen.blit(surf, (0, 0))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
