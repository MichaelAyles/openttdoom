"""Tests for stamping a CHIP-8 framebuffer onto the map as a grid of tiles.

These reuse the synthetic OTTN buffer approach from test_sav_writer (no real OpenTTD): build
a fake save, stamp a tiny known frame, and assert exactly the right tiles became rail and the
rest stayed clear. They pin the geometry contract stamp_framebuffer promises: a lit pixel at
(row, col) maps to a scale x scale block at (origin_x + col*scale, origin_y + row*scale).
"""
import numpy as np
import pytest

from sav_writer import (Sav, ARRAYS, MP_RAILWAY, MP_CLEAR,
                        TRACK_BIT_CROSS, stamp_framebuffer)

# reuse the exact synthetic-OTTN builder the existing suite uses.
from test_sav_writer import _make_fake_sav, _write


def _is_rail(s, x, y):
    t = s.chunks["MAPT"][0]
    i = y * s.size_x + x
    return (s.data[t + i] >> 4) == MP_RAILWAY


def test_stamp_3x3_frame_scale2(tmp_path):
    """A known 3x3 frame at scale 2 on a 16x16 map: exactly the lit-pixel blocks become rail."""
    size = 16
    s = Sav(_write(tmp_path, _make_fake_sav(size_x=size, n_tiles=size * size)))
    s.set_size_x(size)

    # a small recognizable pattern (an X-ish shape), rows=height, cols=width.
    frame = np.array([
        [1, 0, 1],
        [0, 1, 0],
        [1, 0, 1],
    ], dtype=np.uint8)
    scale = 2
    origin_x, origin_y = 4, 4

    stamped = stamp_framebuffer(s, frame, origin_x, origin_y, scale=scale)

    # 5 lit pixels, each a 2x2 block -> 5 * 4 = 20 tiles.
    assert stamped == 5 * scale * scale == 20

    # build the exact set of tiles that should be rail.
    expected = set()
    for row in range(3):
        for col in range(3):
            if frame[row, col]:
                for dy in range(scale):
                    for dx in range(scale):
                        expected.add((origin_x + col * scale + dx,
                                      origin_y + row * scale + dy))

    # every tile in the map: rail iff in expected, clear otherwise.
    t = s.chunks["MAPT"][0]
    for y in range(size):
        for x in range(size):
            i = y * size + x
            tt = s.data[t + i] >> 4
            if (x, y) in expected:
                assert tt == MP_RAILWAY, f"({x},{y}) should be rail"
                # and it should carry the cross trackbits encoding.
                m5 = s.chunks["MAP5"][0]
                assert s.data[m5 + i] == TRACK_BIT_CROSS
            else:
                assert tt == MP_CLEAR, f"({x},{y}) should be clear, got type {tt}"


def test_dark_pixels_left_as_grass(tmp_path):
    """An all-zero frame stamps nothing; the canvas stays entirely clear."""
    size = 8
    s = Sav(_write(tmp_path, _make_fake_sav(size_x=size, n_tiles=size * size)))
    s.set_size_x(size)
    frame = np.zeros((3, 3), dtype=np.uint8)
    assert stamp_framebuffer(s, frame, 1, 1, scale=2) == 0
    # nothing converted.
    t = s.chunks["MAPT"][0]
    assert all((s.data[t + i] >> 4) == MP_CLEAR for i in range(size * size))


def test_single_lit_pixel_block_position(tmp_path):
    """One lit pixel at (row=1, col=2) lands its block at the documented offset."""
    size = 16
    s = Sav(_write(tmp_path, _make_fake_sav(size_x=size, n_tiles=size * size)))
    s.set_size_x(size)
    frame = np.zeros((3, 3), dtype=np.uint8)
    frame[1, 2] = 1                       # row 1, col 2
    scale, ox, oy = 3, 2, 5
    stamped = stamp_framebuffer(s, frame, ox, oy, scale=scale)
    assert stamped == scale * scale == 9
    # block spans x = ox + col*scale .. , y = oy + row*scale ..
    bx, by = ox + 2 * scale, oy + 1 * scale   # (8, 8)
    for dy in range(scale):
        for dx in range(scale):
            assert _is_rail(s, bx + dx, by + dy)
    # a tile just outside the block stays clear.
    assert not _is_rail(s, bx - 1, by)
    assert not _is_rail(s, bx, by - 1)


def test_bounds_checked_offmap(tmp_path):
    """A block that runs off the map edge counts only the tiles that landed on the map."""
    size = 8
    s = Sav(_write(tmp_path, _make_fake_sav(size_x=size, n_tiles=size * size)))
    s.set_size_x(size)
    # single lit pixel, scale 4, origin near the corner so the block overhangs.
    frame = np.ones((1, 1), dtype=np.uint8)
    scale = 4
    # origin (6,6): block would cover x,y in 6..9, but the map is 0..7, so only the
    # 2x2 sub-block at x,y in 6..7 is on-map.
    stamped = stamp_framebuffer(s, frame, 6, 6, scale=scale)
    assert stamped == 4, f"expected 4 on-map tiles, got {stamped}"
    for y in (6, 7):
        for x in (6, 7):
            assert _is_rail(s, x, y)


def test_skips_nonclear_under_block(tmp_path):
    """A water tile under the block is left untouched and not counted."""
    size = 8
    s = Sav(_write(tmp_path, _make_fake_sav(size_x=size, n_tiles=size * size)))
    s.set_size_x(size)
    from sav_writer import MP_WATER
    # mark one tile inside where the 2x2 block will land as water.
    ox, oy, scale = 2, 2, 2
    t = s.chunks["MAPT"][0]
    water_xy = (3, 3)                     # inside block x,y in 2..3
    s.data[t + water_xy[1] * size + water_xy[0]] = (MP_WATER << 4)
    frame = np.ones((1, 1), dtype=np.uint8)
    stamped = stamp_framebuffer(s, frame, ox, oy, scale=scale)
    assert stamped == 3, f"3 of 4 tiles stampable, got {stamped}"
    # the water tile is still water.
    assert (s.data[t + water_xy[1] * size + water_xy[0]] >> 4) == MP_WATER


def test_requires_2d_frame(tmp_path):
    size = 4
    s = Sav(_write(tmp_path, _make_fake_sav()))
    s.set_size_x(size)
    with pytest.raises(ValueError):
        stamp_framebuffer(s, np.array([1, 0, 1], dtype=np.uint8), 0, 0)
