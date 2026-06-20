"""Write openttdoom designs straight into an OpenTTD savegame, no runtime build.

The GameScript path builds a design tile by tile at runtime: it needs a company, money,
flat land, and minutes of wall-clock for a big design. This writer sidesteps all of that by
editing the savegame's map tile arrays directly, so a design of any size appears instantly.

How it works (and why it is robust):
  - OpenTTD must be configured to save UNCOMPRESSED (savegame_format = none), giving an `OTTN`
    file whose map is stored as flat per-tile byte arrays (see src/saveload/map_sl.cpp).
  - We start from a real base save (made by OpenTTD: flat map, one company), so every mandatory
    chunk and all game state is already valid. We only OVERWRITE tile bytes IN PLACE, same size,
    so no chunk needs reframing and the rest of the save is untouched.
  - Each tile spans several arrays: type/MAPT, owner/MAPO (m1), m2/MAP2 (u16), m3/M3LO, m4/M3HI,
    m5/MAP5, m6/MAPE, m7/MAP7, m8/MAP8 (u16). A plain rail tile is (per rail_map.h MakeRailNormal):
      type high nibble = MP_RAILWAY (1);  m1 = owner;  m5 = RailTileType::Normal(0)<<6 | trackbits;
      m8 = rail type (0);  m2=m3=m4=m7=0;  m6 high bits 0.
    Track bits: X axis (NE-SW) = 1, Y axis (NW-SE) = 2, cross = 3 (track_type.h).

A scenario's routes are axis-aligned runs plus bridge crossings; we lay a CROSS tile (both
track bits) at every route tile so the layout reads clearly on the minimap. Bridges in the
scenario are drawn as cross tiles too (the point is the visible CPU, not a working signal).

CLI:
  python tools/sav_writer.py <scenario_or_netlist.json> --base <base.sav> --out <name>
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for d in ("synth", "place_and_route", "hdl", "scenarios"):
    sys.path.insert(0, os.path.join(REPO, d))

# tile field constants (from OpenTTD 15.3 source: tile_type.h, rail_map.h, company_type.h)
MP_CLEAR = 0
MP_RAILWAY = 1
MP_WATER = 6
MP_VOID = 7
OWNER_NONE = 0x10
RAILTYPE_RAIL = 0
TRACK_BIT_X = 1
TRACK_BIT_Y = 2
TRACK_BIT_CROSS = 3

# map arrays: tag -> bytes-per-tile
ARRAYS = {
    "MAPT": 1, "MAPH": 1, "MAPO": 1, "MAP2": 2,
    "M3LO": 1, "M3HI": 1, "MAP5": 1, "MAPE": 1, "MAP7": 1, "MAP8": 2,
}


class Sav:
    """An uncompressed OTTN savegame with editable map tile arrays."""

    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.data = bytearray(f.read())
        if self.data[:4] != b"OTTN":
            raise ValueError(f"{path} is not an uncompressed OTTN save "
                             "(set savegame_format = none and re-save)")
        self.chunks = {}      # tag -> (data_offset, length, bytes_per_tile)
        self._locate()
        # tiles = MAPT length (1 byte per tile)
        self.n_tiles = self.chunks["MAPT"][1]
        # square map assumed (openttdoom uses power-of-two square maps)
        self.size_x = int(round(self.n_tiles ** 0.5))
        if self.size_x * self.size_x != self.n_tiles:
            # fall back: most openttdoom maps are square; otherwise the caller passes size
            self.size_x = 0

    def _locate(self) -> None:
        for tag, w in ARRAYS.items():
            tagb = tag.encode()
            off = self.data.find(tagb)
            while off != -1:
                hdr = self.data[off + 4:off + 8]
                m = hdr[0]
                ln = ((m >> 4) << 24) | (hdr[1] << 16) | (hdr[2] << 8) | hdr[3]
                # validate: this is a RIFF chunk whose length is a whole tile array
                if (m & 0x0F) == 0 and ln > 0 and ln % w == 0:
                    self.chunks[tag] = (off + 8, ln, w)
                    break
                off = self.data.find(tagb, off + 1)
            if tag not in self.chunks and tag not in ("MAPH",):
                raise ValueError(f"chunk {tag} not found in save")

    def set_size_x(self, size_x: int) -> None:
        self.size_x = size_x

    def _clear_ref(self) -> dict:
        """Sample one real MP_CLEAR tile so we can replicate valid clear-ground bytes."""
        t = self.chunks["MAPT"][0]
        for i in range(self.n_tiles):
            if (self.data[t + i] >> 4) == MP_CLEAR:
                ref = {"type_lo": self.data[t + i] & 0x0F}
                for tag, (off, ln, w) in self.chunks.items():
                    if w == 1:
                        ref[tag] = self.data[off + i]
                    else:
                        ref[tag] = (self.data[off + i * 2] << 8) | self.data[off + i * 2 + 1]
                return ref
        raise ValueError("no clear tile found to sample")

    def flatten(self, height: int = 1) -> int:
        """Make a plain canvas: uniform height and uniform grass for every non-void tile.

        Every inner tile (water, trees, rocky ground, ...) becomes the same clear grass tile
        at the same height, so the stamped design sits on a featureless level plain with no
        gaps and no minimap clutter. Void border tiles are left untouched. Returns the number
        of tiles converted (every non-clear inner tile).
        """
        ref = self._clear_ref()
        mapt = self.chunks["MAPT"][0]
        maph = self.chunks.get("MAPH", (None,))[0]
        non_h = [(tag, off, w) for tag, (off, ln, w) in self.chunks.items()
                 if tag not in ("MAPT", "MAPH")]
        converted = 0
        for i in range(self.n_tiles):
            tt = self.data[mapt + i] >> 4
            if tt == MP_VOID:
                continue
            if maph is not None:
                self.data[maph + i] = height
            if tt == MP_CLEAR:
                continue
            # replace this feature with the sampled clear grass tile
            self.data[mapt + i] = (MP_CLEAR << 4) | ref["type_lo"]
            for tag, off, w in non_h:
                if w == 1:
                    self.data[off + i] = ref[tag] & 0xFF
                else:
                    self.data[off + i * 2] = (ref[tag] >> 8) & 0xFF
                    self.data[off + i * 2 + 1] = ref[tag] & 0xFF
            converted += 1
        return converted

    def _idx(self, x: int, y: int) -> int:
        return y * self.size_x + x

    def _put(self, tag: str, idx: int, value: int) -> None:
        off, ln, w = self.chunks[tag]
        if w == 1:
            self.data[off + idx] = value & 0xFF
        else:
            # big-endian u16 (OpenTTD save byte order)
            self.data[off + idx * 2] = (value >> 8) & 0xFF
            self.data[off + idx * 2 + 1] = value & 0xFF

    def rail(self, x: int, y: int, trackbits: int = TRACK_BIT_CROSS, owner: int = 0) -> bool:
        """Stamp a plain rail tile at (x, y). Returns False if the tile was skipped.

        Only genuine MP_CLEAR tiles are converted. Stamping over water, houses, etc. would
        leave that feature's data in the other arrays and produce an invalid rail tile that
        OpenTTD rejects on load, so we skip those tiles (and the caller reports the count).
        """
        if self.size_x == 0:
            raise ValueError("map size unknown; call set_size_x()")
        if not (0 <= x < self.size_x and 0 <= y < self.size_x):
            return False
        i = self._idx(x, y)
        t = self.chunks["MAPT"][0]
        # only convert clear ground (tile type high nibble == MP_CLEAR == 0)
        if (self.data[t + i] >> 4) != 0:
            return False
        # set tile type high nibble to rail, preserve the low nibble (tropic zone etc.)
        self.data[t + i] = (self.data[t + i] & 0x0F) | (MP_RAILWAY << 4)
        self._put("MAPO", i, owner)
        self._put("MAP5", i, (0 << 6) | (trackbits & 0x3F))
        self._put("MAP2", i, 0)
        self._put("M3LO", i, 0)
        self._put("M3HI", i, 0)
        self._put("MAP7", i, 0)
        self._put("MAP8", i, RAILTYPE_RAIL)
        # clear m6 high bits (keep low 2: docking/tropic-ish); 0 is safe for a fresh rail tile
        if "MAPE" in self.chunks:
            off6 = self.chunks["MAPE"][0]
            self.data[off6 + i] &= 0x03
        return True

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.data)


def _route_trackbits(path):
    """Per-tile track bits for a route path: X for a horizontal step, Y for a vertical step.

    A tile that both enters and leaves along the same axis gets that axis's single track; a
    corner (axis changes) gets a cross so the two segments still connect. This makes long runs
    render as clean straight rail up close instead of a plus on every tile.
    """
    bits = {}
    for k, (x, y) in enumerate(path):
        axes = 0
        if k > 0:
            px, py = path[k - 1]
            axes |= TRACK_BIT_X if py == y else TRACK_BIT_Y
        if k < len(path) - 1:
            nx, ny = path[k + 1]
            axes |= TRACK_BIT_X if ny == y else TRACK_BIT_Y
        bits[(x, y)] = axes or TRACK_BIT_CROSS
    return bits


def stamp_scenario(sav: Sav, scenario, owner: int = 0, directional: bool = False) -> tuple:
    """Lay rail for every cell footprint and route tile. Returns (stamped, skipped).

    directional=True lays single-axis track along straight route runs (cleaner close up);
    otherwise every tile is a cross (denser, clearer on a zoomed-out minimap).
    """
    stamped = skipped = 0
    for c in scenario.cells:
        for (x, y) in c.occupied():
            if sav.rail(x, y, TRACK_BIT_CROSS, owner):
                stamped += 1
            else:
                skipped += 1
    for r in scenario.routes:
        tb = _route_trackbits(r.path) if directional else None
        for (x, y) in r.path:
            bits = tb[(x, y)] if tb else TRACK_BIT_CROSS
            if sav.rail(x, y, bits, owner):
                stamped += 1
            else:
                skipped += 1
    return stamped, skipped


def stamp_framebuffer(sav: Sav, frame, origin_x: int, origin_y: int,
                      scale: int = 8, owner: int = 0) -> int:
    """Stamp a CHIP-8 framebuffer onto the map as a grid of tiles.

    `frame` is a 2D numpy array of 0/1 with rows=height, cols=width (the chip8.display
    layout). Each LIT pixel (1) becomes a scale x scale solid block of rail tiles, dark
    pixels (0) are left as grass. The block for pixel (row, col) covers map tiles
    (origin_x + col*scale .. +scale-1, origin_y + row*scale .. +scale-1), so the image reads
    the right way up: row 0 at the top (smallest y), col 0 at the left.

    Only genuine clear tiles are converted (sav.rail already skips water, houses, etc.), and
    tiles off the map are skipped, so this is safe on any base save. Returns the number of rail
    tiles actually stamped (lit-pixel count times scale^2, minus any tiles that fell off the
    map or were not clear).
    """
    import numpy as np

    frame = np.asarray(frame)
    if frame.ndim != 2:
        raise ValueError(f"frame must be 2D (rows, cols), got shape {frame.shape}")
    if scale < 1:
        raise ValueError(f"scale must be >= 1, got {scale}")
    if sav.size_x == 0:
        raise ValueError("map size unknown; call set_size_x()")

    height, width = frame.shape
    stamped = 0
    for row in range(height):
        for col in range(width):
            if not frame[row, col]:
                continue
            bx = origin_x + col * scale
            by = origin_y + row * scale
            for dy in range(scale):
                for dx in range(scale):
                    if sav.rail(bx + dx, by + dy, TRACK_BIT_CROSS, owner):
                        stamped += 1
    return stamped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design", nargs="?",
                    help="scenario JSON, or a netlist JSON to place+route first "
                         "(omit when using --frame)")
    ap.add_argument("--base", required=True, help="uncompressed OTTN base save")
    ap.add_argument("--out", required=True, help="output .sav path")
    ap.add_argument("--offset", type=int, default=8, help="shift design away from map edge")
    ap.add_argument("--size", type=int, default=0, help="override map width in tiles")
    ap.add_argument("--flatten", action="store_true",
                    help="level the map and remove water for a plain canvas")
    ap.add_argument("--directional", action="store_true",
                    help="single-axis track along straight runs (cleaner close up)")
    # framebuffer-to-tiles mode: stamp a CHIP-8 frame as a block-pixel image.
    ap.add_argument("--frame",
                    help="stamp a framebuffer instead of a design. Either a .npy of a 0/1 "
                         "array, or 'raycaster[:HEADING]' / 'rom:PATH:CYCLES' to run a ROM")
    ap.add_argument("--scale", type=int, default=8,
                    help="tiles per pixel edge for --frame (lit pixel -> scale x scale block)")
    a = ap.parse_args()

    sav = Sav(a.base)
    if a.size:
        sav.set_size_x(a.size)
    if a.flatten:
        conv = sav.flatten()
        print(f"flattened canvas: {conv} water tiles converted to grass")

    if a.frame:
        frame = _load_frame(a.frame)
        lit = int((frame != 0).sum())
        stamped = stamp_framebuffer(sav, frame, a.offset, a.offset, scale=a.scale)
        sav.save(a.out)
        h, w = frame.shape
        print(f"stamped frame {w}x{h} ({lit} lit pixels) at scale {a.scale} into {a.out}: "
              f"{stamped} rail tiles (map width {sav.size_x})")
        return 0

    if not a.design:
        ap.error("a design JSON is required unless --frame is given")

    from scenario import Scenario
    import json
    raw = json.load(open(a.design))
    if "routes" in raw and "cells" in raw and "map_x" in raw:
        sc = Scenario.from_dict(raw)
    else:
        from netlist import Netlist
        from emit import build_scenario
        nl = Netlist.from_dict(raw)
        out = build_scenario(nl)
        sc = out[0] if isinstance(out, tuple) else out

    # shift by offset so nothing sits on the map border
    if a.offset:
        for c in sc.cells:
            c.x += a.offset; c.y += a.offset
            for p in c.inputs:
                p.x += a.offset; p.y += a.offset
            if c.output:
                c.output.x += a.offset; c.output.y += a.offset
        for r in sc.routes:
            r.path = [(x + a.offset, y + a.offset) for (x, y) in r.path]

    stamped, skipped = stamp_scenario(sav, sc, directional=a.directional)
    sav.save(a.out)
    note = f", {skipped} skipped (non-clear tiles, e.g. water)" if skipped else ""
    print(f"stamped {stamped} rail tiles into {a.out} (map width {sav.size_x}){note}")
    return 0


def _load_frame(spec: str):
    """Resolve a --frame spec into a 0/1 numpy array.

    Accepted forms:
      PATH.npy            a saved 0/1 frame array
      raycaster           the raycaster ROM, default heading 3
      raycaster:HEADING   the raycaster ROM at the given heading
      rom:PATH:CYCLES     run any .ch8 for CYCLES instructions
    """
    import numpy as np

    if spec.endswith(".npy"):
        return np.load(spec)

    # frame_export lives in golden/, which conftest/the CLI path setup puts on sys.path.
    sys.path.insert(0, os.path.join(REPO, "golden"))
    import frame_export

    if spec == "raycaster" or spec.startswith("raycaster:"):
        heading = int(spec.split(":", 1)[1]) if ":" in spec else 3
        return frame_export.get_raycaster_frame(heading)
    if spec.startswith("rom:"):
        _, path, cycles = spec.split(":", 2)
        return frame_export.get_rom_frame(path, int(cycles))
    raise ValueError(f"unrecognised --frame spec {spec!r} "
                     "(use PATH.npy, raycaster[:H], or rom:PATH:CYCLES)")


if __name__ == "__main__":
    raise SystemExit(main())
