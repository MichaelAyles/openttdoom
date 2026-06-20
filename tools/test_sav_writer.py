"""Tests for the direct savegame writer.

These check the in-place tile editing logic against a synthetic OTTN-framed buffer (no real
OpenTTD needed): chunk location, the rail-tile byte encoding, clear-tile-only stamping, and
that flatten removes water. The full round trip (load in OpenTTD, screenshot) is verified
manually, see out_screens/.
"""
import struct

import pytest

from sav_writer import (Sav, ARRAYS, MP_RAILWAY, MP_WATER, MP_CLEAR,
                        TRACK_BIT_CROSS, RAILTYPE_RAIL)


def _make_fake_sav(size_x=4, n_tiles=16):
    """Build a minimal OTTN buffer: header + one RIFF chunk per map array, all-zero tiles.

    Tile 0 is left as clear (type 0); tile 5 is marked water (type MP_WATER) to test flatten.
    """
    buf = bytearray(b"OTTN" + b"\x01\x6a\x00\x00")
    for tag, w in ARRAYS.items():
        ln = n_tiles * w
        buf += tag.encode()
        # RIFF length header: m=0, then byte<<16, then u16 big-endian
        buf += bytes([0x00, (ln >> 16) & 0xFF]) + struct.pack(">H", ln & 0xFFFF)
        buf += bytes(ln)
    # 4 zero bytes terminate the chunk list
    buf += b"\x00\x00\x00\x00"
    return buf


def _write(tmp_path, buf):
    p = tmp_path / "fake.sav"
    p.write_bytes(buf)
    return str(p)


def test_locates_all_chunks(tmp_path):
    s = Sav(_write(tmp_path, _make_fake_sav()))
    for tag in ARRAYS:
        assert tag in s.chunks, f"{tag} not located"
    assert s.n_tiles == 16


def test_rail_encoding(tmp_path):
    s = Sav(_write(tmp_path, _make_fake_sav()))
    s.set_size_x(4)
    assert s.rail(1, 1, TRACK_BIT_CROSS) is True
    i = 1 * 4 + 1
    # type high nibble == MP_RAILWAY
    t = s.chunks["MAPT"][0]
    assert (s.data[t + i] >> 4) == MP_RAILWAY
    # m5 == RailTileType::Normal(0)<<6 | trackbits
    m5 = s.chunks["MAP5"][0]
    assert s.data[m5 + i] == TRACK_BIT_CROSS
    # m8 (u16) == rail type 0
    m8 = s.chunks["MAP8"][0]
    assert s.data[m8 + i * 2] == 0 and s.data[m8 + i * 2 + 1] == RAILTYPE_RAIL


def test_skips_nonclear_tiles(tmp_path):
    buf = _make_fake_sav()
    s = Sav(_write(tmp_path, buf))
    s.set_size_x(4)
    # mark tile (2,0) [index 2] as water by hand, then try to rail it
    t = s.chunks["MAPT"][0]
    s.data[t + 2] = (MP_WATER << 4)
    assert s.rail(2, 0) is False           # water is not stamped
    assert (s.data[t + 2] >> 4) == MP_WATER  # left untouched


def test_flatten_converts_water(tmp_path):
    s = Sav(_write(tmp_path, _make_fake_sav()))
    s.set_size_x(4)
    t = s.chunks["MAPT"][0]
    s.data[t + 5] = (MP_WATER << 4)         # one water tile
    conv = s.flatten()
    assert conv == 1
    assert (s.data[t + 5] >> 4) == MP_CLEAR  # now grass, rail can be stamped
    assert s.rail(1, 1) is True
