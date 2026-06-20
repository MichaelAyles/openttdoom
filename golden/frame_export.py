"""Export CHIP-8 framebuffers as 0/1 numpy arrays for the tile renderer to consume.

This is the bridge between the M1 golden model and the framebuffer-to-tiles phase: it
runs a ROM for real in golden/chip8.Chip8 (no faked frames) and hands back the 64x32
display buffer as a uint8 array of 0/1. The renderer (tools/sav_writer.stamp_framebuffer)
turns each lit pixel into a solid block of rail tiles on an OpenTTD map.

The two sources:
  - get_raycaster_frame(heading) runs the hand-assembled raycaster ROM (golden/raycaster.py),
    which executes only standard CHIP-8 opcodes in the golden interpreter and draws the
    pseudo-3D corridor for a baked-in heading.
  - get_rom_frame(rom_path, cycles) runs any .ch8 file for a fixed number of instructions and
    returns the framebuffer, e.g. the Timendus IBM logo at vendor/chip8/roms/2-ibm-logo.ch8.

The main saves a handful of frames as .npy (the renderer's input) and as preview PNGs (so a
human can eyeball them) into golden/out/, and prints each frame's lit-pixel count.
"""

from __future__ import annotations

import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "out")
ROM_DIR = os.path.join(REPO, "vendor", "chip8", "roms")

# The IBM logo ROM clears the screen, draws its bitmap, then loops, so the framebuffer is
# stable from ~20 cycles onward (230 lit pixels). 30 matches the count pinned in
# golden/test_chip8.py, with comfortable headroom past full render.
IBM_CYCLES = 30


def get_raycaster_frame(heading: int = 3) -> np.ndarray:
    """Run the raycaster ROM for a heading and return its 64x32 display as uint8 0/1.

    This assembles and executes the real ROM in golden/chip8.Chip8 (via raycaster.render_rom),
    not the pure-Python oracle, so it exercises the same opcode path the train machine has to
    match. The returned array is rows=height(32), cols=width(64), values 0 or 1.
    """
    import raycaster

    m = raycaster.render_rom(heading)
    # display is already uint8 0/1; copy so callers cannot mutate interpreter state.
    return np.ascontiguousarray(m.display, dtype=np.uint8)


def get_rom_frame(rom_path: str, cycles: int) -> np.ndarray:
    """Run any .ch8 ROM for `cycles` instructions and return the 64x32 display as uint8 0/1.

    Timer ticks are paced the usual way (viewer.run_rom). Pick `cycles` large enough for the
    ROM to finish its render: the IBM logo completes by ~20, so IBM_CYCLES (30) is safe.
    """
    import viewer

    m = viewer.run_rom(rom_path, cycles)
    return np.ascontiguousarray(m.display, dtype=np.uint8)


def _save_preview(frame: np.ndarray, path: str, scale: int = 8) -> None:
    """Save a 0/1 frame as a 1-bit PNG, lit pixels white, scaled up to be eyeballable.

    Mirrors viewer.save_png (lit -> 255, NEAREST upscale, convert to true 1-bit) but works on
    a bare numpy array so it does not need a live Chip8 instance.
    """
    from PIL import Image

    h, w = frame.shape
    buf = (frame * 255).astype(np.uint8)
    img = Image.fromarray(buf, mode="L")
    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    img.convert("1").save(path)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    frames: list[tuple[str, np.ndarray]] = []

    # a few raycaster headings, so the render phase has a choice of recognizable scenes.
    for heading in (3, 0, 8):
        frame = get_raycaster_frame(heading)
        frames.append((f"frame_raycaster_h{heading}", frame))

    # the Timendus IBM logo, a fixed bitmap, good for a visually obvious render check.
    ibm_path = os.path.join(ROM_DIR, "2-ibm-logo.ch8")
    if os.path.exists(ibm_path):
        frames.append(("frame_ibm", get_rom_frame(ibm_path, IBM_CYCLES)))
    else:
        print(f"note: {ibm_path} missing, skipping IBM logo frame")

    for name, frame in frames:
        npy_path = os.path.join(OUT_DIR, name + ".npy")
        png_path = os.path.join(OUT_DIR, name + ".png")
        np.save(npy_path, frame)
        _save_preview(frame, png_path)
        lit = int(frame.sum())
        print(f"{name}: shape {frame.shape} lit {lit} pixels -> {npy_path}, {png_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
