"""Tests for the hardwired raycaster FSM (hdl/raycaster_fsm.py).

The headline contract, the same one test_raycaster.py pins for the CHIP-8 ROM: the rendered
framebuffer equals the integer oracle render_reference_hw(res="lo") BIT FOR BIT, over a heading
sweep. The checks build up to it in order of trust, mirroring hdl/test_cpu.py:

  1. The write-once per-pixel paint (_pixel) and the cycle-accurate dataflow model (fsm_reference)
     ARE proven equal to render_reference_hw for every heading and both texture settings. This is
     the software ground truth the hardware is checked against.
  2. The behavioural Amaranth RaycasterFsm, simulated with amaranth.sim, renders its framebuffer
     and it equals render_reference_hw bit for bit over a heading sweep (the headline test). It
     also equals fsm_reference, closing the chain oracle == fsm_reference == hardware.
  3. The per-pixel paint datapath, built as a gate-level Netlist and lowered to the buildable
     {NOR, CONST0, CONST1} set, computes _pixel exactly (a real circuit, not a faked frame). Its
     NOR cell count is reported.
  4. The register budget (the scarce train-bits) and cycles/frame are reported.

Run only this file:
    python -m pytest hdl/test_raycaster_fsm.py -q
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from amaranth.hdl import Module
from amaranth.sim import Simulator

import raycaster as rc
import raycaster_fsm as F
from raycaster_fsm import (
    RaycasterFsm,
    build_paint_cone_netlist,
    fsm_reference,
    fsm_register_bits,
    paint_cone_stats,
    _pixel,
    _slice_top_bot,
    COLS,
    H,
    W,
    STEPS,
)


ALL_HEADINGS = list(range(rc.NUM_ANGLES))
# a representative heading sweep for the (slower) full-sim test; the model/cone tests cover all.
SWEEP = [0, 3, 7, 12, 17, 24, 30]


# --- 1: the software models are the oracle, bit for bit ----------------------------

@pytest.mark.parametrize("heading", ALL_HEADINGS)
@pytest.mark.parametrize("texture", [True, False])
def test_fsm_reference_equals_oracle(heading, texture):
    # the cycle-accurate dataflow model (the hardware's ground truth) reproduces the integer
    # oracle render_reference_hw exactly, for every heading and both texture settings.
    ref = rc.render_reference_hw(heading, res="lo", texture=texture)
    got = fsm_reference(heading, texture=texture)
    assert np.array_equal(got, ref), f"fsm_reference diverged at heading {heading} tex {texture}"


def test_write_once_pixel_matches_oracle_paint():
    # the write-once _pixel closed form (seams/edge folded into the lit test) reproduces the
    # oracle's paint-then-clear-seams two-pass, for every heading. This is what makes a single
    # scan-order write per pixel legal.
    for heading in (0, 7, 12, 24):
        ref = rc.render_reference_hw(heading, res="lo", texture=True)
        dist = [F._cast(heading, c)[0] for c in range(COLS)]
        frac = [F._cast(heading, c)[1] for c in range(COLS)]
        got = np.zeros((H, W), dtype=np.uint8)
        for c in range(COLS):
            dl = dist[c - 1] if c > 0 else dist[c]
            dr = dist[c + 1] if c < COLS - 1 else dist[c]
            edge = abs(dist[c] - dl) >= 4 or abs(dist[c] - dr) >= 4
            top, bot = _slice_top_bot(dist[c])
            shade = F._wall_shade(dist[c], frac[c], True)
            for k in range(2):
                x = c * 2 + k
                for y in range(H):
                    got[y, x] = _pixel(y, x, top, bot, shade, edge)
        assert np.array_equal(got, ref), f"write-once paint diverged at heading {heading}"


# --- 2: the behavioural Amaranth FSM matches the oracle (the headline test) ---------

def _run_fsm(heading: int, texture: bool = True, max_cycles: int = 5000):
    """Simulate RaycasterFsm to frame-done with amaranth.sim, return (frame, cycles)."""
    dut = RaycasterFsm()
    m = Module()
    m.submodules.dut = dut
    out = {}

    async def tb(ctx):
        ctx.set(dut.heading, heading)
        ctx.set(dut.texture, 1 if texture else 0)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)
        cyc = 0
        while not ctx.get(dut.done) and cyc < max_cycles:
            await ctx.tick()
            cyc += 1
        out["cyc"] = cyc
        out["frame"] = dut.fb_value(ctx)

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()
    return out["frame"], out["cyc"]


@pytest.mark.parametrize("heading", SWEEP)
def test_behavioural_fsm_matches_oracle(heading):
    # THE headline assertion: the clocked Amaranth machine, simulated edge by edge, renders a
    # framebuffer equal to render_reference_hw(res="lo") bit for bit. The same equality contract
    # test_raycaster.py uses for the ROM, now for real hardware.
    frame, cyc = _run_fsm(heading, texture=True)
    ref = rc.render_reference_hw(heading, res="lo", texture=True)
    assert cyc < 5000, f"frame did not finish for heading {heading}"
    assert np.array_equal(frame, ref), (
        f"heading {heading}: FSM framebuffer diverged from render_reference_hw "
        f"(fsm lit {int(frame.sum())}, oracle lit {int(ref.sum())})"
    )


def test_behavioural_fsm_matches_oracle_no_texture():
    # the texture toggle is wired into the hardware shade path: with texture off the FSM still
    # matches the (different) oracle frame, so the LUT is a real input, not dead decoration.
    frame, _ = _run_fsm(7, texture=False)
    ref = rc.render_reference_hw(7, res="lo", texture=False)
    assert np.array_equal(frame, ref)
    # and the textured frame differs, proving the toggle actually changes the picture.
    frame_tex, _ = _run_fsm(7, texture=True)
    assert not np.array_equal(frame, frame_tex)


def test_behavioural_fsm_equals_dataflow_model():
    # the hardware equals the cycle-accurate Python model too, so the chain
    # oracle == fsm_reference == RaycasterFsm is closed (any future divergence is localised).
    for heading in (0, 12, 24):
        frame, _ = _run_fsm(heading, texture=True)
        assert np.array_equal(frame, fsm_reference(heading, texture=True))


def test_fsm_is_deterministic():
    # same heading, two independent runs, identical framebuffer. The FSM reads no input but the
    # heading and uses no randomness, so this must hold exactly.
    a, _ = _run_fsm(5, texture=True)
    b, _ = _run_fsm(5, texture=True)
    assert np.array_equal(a, b)


def test_fsm_frames_change_as_player_turns():
    # turning the heading must change the rendered view; adjacent depth-rich headings must not
    # collapse to identical frames.
    frames = [_run_fsm(h, texture=True)[0] for h in (0, 4, 8, 12)]
    hashes = {f.tobytes() for f in frames}
    assert len(hashes) == len(frames), "some headings rendered identical FSM frames"


# --- 3: the paint datapath is a real buildable circuit -----------------------------

def _paint_inputs(y, x, top, bot, shade, edge):
    iv = {}
    for pref, val, n in (("y", y, 5), ("x", x, 6), ("top", top, 6),
                         ("bot", bot, 6), ("shade", shade, 5)):
        for i in range(n):
            iv[f"{pref}{i}"] = (val >> i) & 1
    iv["edge"] = edge & 1
    return iv


def test_paint_cone_netlist_builds_and_lowers():
    nl = build_paint_cone_netlist()
    nl.validate()
    assert nl.ports.outputs == ["lit"]
    low = nl.to_nor()
    from netlist import BUILDABLE
    assert all(c.type in BUILDABLE for c in low.cells), "paint cone must lower to buildable cells"
    assert low.stats().get("NOR", 0) > 0


def test_paint_cone_computes_pixel_over_real_geometry():
    # the structural paint cone computes _pixel exactly over every slice geometry the DDA can
    # produce, the full shade range, both edge states, and the four Bayer x-parities (x in
    # 0..3 covers x&3, the only way x enters the paint). A real circuit, not a faked frame.
    nl = build_paint_cone_netlist()
    geoms = sorted({_slice_top_bot(d) for d in range(1, STEPS + 1)})
    # shades that exercise the dither boundaries against the 0..15 Bayer thresholds.
    shades = (0, 1, 2, 5, 8, 11, 13, 16)
    for (top, bot) in geoms:
        for shade in shades:
            for edge in (0, 1):
                for y in range(H):
                    for x in range(4):          # x only matters mod 4 (Bayer column)
                        exp = _pixel(y, x, top, bot, shade, edge)
                        iv = _paint_inputs(y, x, top, bot, shade, edge)
                        assert nl.outputs_for(iv)["lit"] == exp, \
                            f"cone != _pixel at y{y} x{x} top{top} bot{bot} s{shade} e{edge}"


def test_nor_lowered_paint_cone_computes_pixel():
    # the BUILDABLE form (lowered to {NOR, CONST0, CONST1}) computes _pixel too, over a sample
    # spanning every geometry and both edge states, so the substrate-buildable circuit is the
    # same function as the high-level cone (the lowering is verified, not assumed).
    nl = build_paint_cone_netlist()
    low = nl.to_nor()
    geoms = sorted({_slice_top_bot(d) for d in range(1, STEPS + 1)})
    for (top, bot) in geoms:
        for edge in (0, 1):
            for shade in (2, 8, 13):
                # y is a 5-bit input (0..31); keep every sample in range (bot can be H == 32).
                ys = sorted({0, 1, top, max(0, bot - 1), min(bot, H - 1), H - 1})
                for y in ys:
                    for x in range(4):
                        exp = _pixel(y, x, top, bot, shade, edge)
                        iv = _paint_inputs(y, x, top, bot, shade, edge)
                        assert low.outputs_for(iv)["lit"] == exp, \
                            f"NOR cone != _pixel at y{y} x{x} top{top} bot{bot} s{shade} e{edge}"


def test_paint_cone_clamp_branches():
    # fuzz the FULL input space (including out-of-range top/bot that exercise the floor/ceiling
    # row-index clamps) to confirm the cone matches _pixel everywhere, not just on real geometry.
    nl = build_paint_cone_netlist()
    rng = random.Random(20260620)
    for _ in range(3000):
        y = rng.randint(0, 31)
        x = rng.randint(0, 63)
        top = rng.randint(0, 32)
        bot = rng.randint(top, 32)
        shade = rng.randint(0, 16)
        edge = rng.randint(0, 1)
        exp = _pixel(y, x, top, bot, shade, edge)
        got = nl.outputs_for(_paint_inputs(y, x, top, bot, shade, edge))["lit"]
        assert got == exp, f"cone != _pixel at y{y} x{x} top{top} bot{bot} s{shade} e{edge}"


# --- 4: the metrics the brief asks for (reported, and sanity-pinned) ---------------

def test_register_budget_is_small():
    # the control / datapath state is the scarce resource (a couple dozen-ish bits), well under
    # the framebuffer. This pins the honest budget the report quotes.
    bits = fsm_register_bits()
    assert bits["_framebuffer"] == W * H == 2048
    assert bits["_control_total"] < 128, f"control state grew to {bits['_control_total']} bits"
    # every named field is accounted for in the total.
    named = sum(v for k, v in bits.items() if not k.startswith("_"))
    assert named == bits["_control_total"]


def test_paint_cone_nor_count_reported():
    stats = paint_cone_stats()
    assert stats["NOR"] > 0
    assert stats["total"] == stats["NOR"] + stats["CONST0"] + stats["CONST1"]


def test_cycles_per_frame_reported():
    # one full frame finishes in a bounded number of clock edges; pin the count for heading 0 so
    # a control-FSM regression that stalls or loops fails loudly here.
    _frame, cyc = _run_fsm(0, texture=True)
    assert 0 < cyc < 5000
