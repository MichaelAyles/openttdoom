"""Render a sequence of raycaster frames to golden/out/ray_*.png.

Each frame is a separate CHIP-8 ROM with a different heading baked in, executed
for real in the golden chip8.Chip8 interpreter (no shortcuts, no faked pixels).
The frames sweep the player's heading so the pseudo-3D corridor visibly rotates.

Run:  python render_raycaster.py
Output: golden/out/ray_00.png .. ray_NN.png plus an ASCII dump to stdout.
"""

from __future__ import annotations

import os

import numpy as np

import raycaster as rc
import viewer

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# the headings to render, as a turn sweep. 32 angles is a full circle; this
# subset sweeps the player's heading through the depth-rich views (the ones that
# look down corridors rather than straight into a near wall), so the pseudo-3D
# perspective visibly rotates frame to frame.
HEADINGS = [29, 30, 31, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def ascii_frame(disp: np.ndarray) -> str:
    return "\n".join("".join("#" if v else "." for v in row) for row in disp)


def main() -> list[str]:
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = []
    for idx, heading in enumerate(HEADINGS):
        m = rc.render_rom(heading)
        # sanity: the real execution must match the pure-python oracle.
        ref = rc.render_reference(heading)
        assert np.array_equal(ref, m.display), f"heading {heading} diverged from oracle"
        path = os.path.join(OUT_DIR, f"ray_{idx:02d}.png")
        viewer.save_png(m, path)
        paths.append(path)
        print(f"frame {idx:02d} heading {heading:2d}: lit {int(m.display.sum()):4d}  -> {path}")
    # print the most depth-revealing frame as ASCII so the corridor is visible
    # in a text log too.
    print("\nheading 0 (looking down the corridor):")
    print(ascii_frame(rc.render_rom(0).display))
    return paths


if __name__ == "__main__":
    main()
