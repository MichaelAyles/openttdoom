"""Close the raycaster FSM through the place-and-route pipeline, IN SOFTWARE.

hdl/raycaster_fsm.py is the hardwired raycaster as a clocked state machine (deliverable B),
matching golden/raycaster.py::render_reference_hw bit for bit in simulation. This module is the
BACKEND closure for it, the same move hdl/cpu.py made for the accumulator CPU: lower the FSM's
combinational cones to a buildable {NOR, CONST0, CONST1} netlist, build a registered (DFF + NOR)
slice that is sequential_equivalent to the behavioural FSM over a frame, run it through the real
place_and_route (register tiles + the clock spine), and reconstruct + verify_equivalence on the
combinational cone. Pure software; nothing here runs OpenTTD.

What is built here, and why a SLICE
-----------------------------------
The full registered raycaster FSM is large: 84 control/datapath register bits plus the 2048-bit
framebuffer output panel, and its per-pixel paint cone alone lowers to ~1419 NOR cells (probed).
This used to be right at the scale where the shared constructive channel router
(place_and_route/channel_route.py) crowded risers and took a route_short fallback (STUCK.md #8).
That has since been FIXED at the router/placement level (wide-fan-in footprints now contain their
pins, stacked same-net pins coalesce instead of forming a blob, and the output-pad side reserves a
clear riser channel), so the ~1419-NOR paint cone now routes 100 percent of nets DRC-clean through
the same shared router, exactly like the 92-cell adder and the 893-cell ALU. See
route_slice_report on build_paint_cone_netlist().to_nor().

This module still keeps both the proven cones and the small representative slices, which are the
cheap fast exemplars used in the tests:

  1. Lowers BOTH combinational cones of the FSM to the buildable set and proves them correct:
       - the per-pixel PAINT cone (build_paint_cone_netlist, already in raycaster_fsm.py), and
       - the per-step DDA CAST cone (build_cast_step_cone_netlist here): advance the ray one
         micro-step, test the map cell, pick the wall fraction, and report hit / hit-distance.
     Both lower via to_nor() to {NOR, CONST0, CONST1} and compute their reference exactly.

  2. Builds a REGISTERED (DFF + NOR) sequential slice, build_cast_march_netlist(): the cast
     datapath wrapped in the ray-position / step registers, marching the DDA one micro-step per
     clock for one column. It is proven sequential_equivalent to the behavioural cast (a Python
     cycle model of the SAME march) over a full column's worth of steps (a frame's inner loop),
     using synth.netlist.sequential_equivalent, the Phase-1 contract.

  3. Routes REPRESENTATIVE SLICES that close 100 percent DRC-clean through the shared channel
     router (the large paint cone now also routes clean, see above; these slices remain the small,
     fast exemplars the tests run). build_route_slice() is the COMBINATIONAL slice, the
     dual-axis DDA ray advance for one column (the per-step position update, the heart of the
     cast); build_seq_route_slice() is the SEQUENTIAL slice, a clocked hit-distance register
     pipeline (register tiles + the clock spine). route_slice_report() places + channel-routes
     either and reports percent routed, DRC count, footprint and bridges. The honest scope is
     reported by frame_pipeline_report(): the full FSM's cell/register/cycle metrics AND the
     slices that route clean.

  4. Emits the combinational slice's Scenario/.nut and reconstructs it (scenario_to_netlist), then
     verify_equivalence, proving the placement preserved the logic (emit_and_reconstruct_slice).

No em-dashes, integer only, deterministic. Nothing here runs OpenTTD: the physical register tile
geometry is Phase-4 (STUCK.md #7), reserved as a footprint exactly as the combinational NOR was.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from netlist import (
    Netlist,
    NetlistBuilder,
    SeqSim,
    equivalent,
    sequential_equivalent,
    simulate_trace,
)

import raycaster as rc
import raycaster_fsm as F
from raycaster_fsm import (
    DIRX_MAG,
    DIRY_MAG,
    SIGNX,
    SIGNY,
    MAP,
    STEPS,
    NUM_ANGLES,
    PLAYER_X,
    PLAYER_Y,
    build_paint_cone_netlist,
)


# ---------------------------------------------------------------------------------
# bus helpers on a NetlistBuilder: small integer datapath built from NOR-only emitters,
# mirroring the style of hdl/cpu.py and hdl/alu.py (lists of net names, bit 0 = LSB).
# ---------------------------------------------------------------------------------

def _bus_in(b: NetlistBuilder, name: str, width: int) -> List[str]:
    return [b.declare_input(f"{name}{i}") for i in range(width)]


def _const_bits(b: NetlistBuilder, value: int, width: int) -> List[str]:
    one, zero = b.const1(), b.const0()
    return [one if (value >> i) & 1 else zero for i in range(width)]


def _mux2_bit(b: NetlistBuilder, sel: str, a: str, c: str) -> str:
    """sel ? c : a."""
    nsel = b.inv(sel)
    return b.or_([b.and_([a, nsel]), b.and_([c, sel])])


def _mux2(b: NetlistBuilder, sel: str, a: List[str], c: List[str]) -> List[str]:
    return [_mux2_bit(b, sel, a[i], c[i]) for i in range(len(a))]


def _ripple_add(b: NetlistBuilder, xb: List[str], yb: List[str], cin: str):
    """n-bit ripple-carry add. Returns (sum_bits, carry_out)."""
    carry = cin
    sums = []
    for i in range(len(xb)):
        axb = b.xor2(xb[i], yb[i])
        s_i = b.xor2(axb, carry)
        ab = b.and_([xb[i], yb[i]])
        cc = b.and_([carry, axb])
        carry = b.or_([ab, cc])
        sums.append(s_i)
    return sums, carry


def _eq_const(b: NetlistBuilder, bus: List[str], value: int) -> str:
    lits = [bus[i] if (value >> i) & 1 else b.inv(bus[i]) for i in range(len(bus))]
    return b.and_(lits)


def _eq_bus(b: NetlistBuilder, xb: List[str], yb: List[str]) -> str:
    return b.and_([b.xnor2(xb[i], yb[i]) for i in range(len(xb))])


def _rom(b: NetlistBuilder, index_bits: List[str], table: List[int], width: int) -> List[str]:
    """Hardwired ROM: a one-hot mux over `table`, `width` output bits. The LUT-as-track ROM
    pattern used by hdl/cpu.py's program ROM and raycaster_fsm.py's paint cone."""
    zero = b.const0()
    n = 1 << len(index_bits)
    onehot = []
    for v in range(n):
        lits = [index_bits[i] if (v >> i) & 1 else b.inv(index_bits[i])
                for i in range(len(index_bits))]
        onehot.append(b.and_(lits) if lits else b.const1())
    outs = []
    for bit in range(width):
        terms = [onehot[v] for v in range(n) if v < len(table) and (table[v] >> bit) & 1]
        outs.append(b.or_(terms) if terms else zero)
    return outs


# ---------------------------------------------------------------------------------
# The DDA cast micro-step, as a combinational reference and as a buildable netlist.
# ---------------------------------------------------------------------------------
#
# One micro-step of the ray march for a given angle index:
#   new_x = x +/- DIRX_MAG[angle]  (minus iff SIGNX[angle])
#   new_y = y +/- DIRY_MAG[angle]
#   cx,cy = new_x>>4, new_y>>4 ; prev_cx,prev_cy = x>>4, y>>4
#   solid = MAP[cy*16 + cx]
#   frac  = (new_y&0xF) if vertical face, (new_x&0xF) if horizontal, dominant axis on a corner.
# This is exactly the body of golden/raycaster.py::_cast_hw and the comb logic in
# RaycasterFsm.elaborate, so the cone and the FSM index the SAME constants.


def cast_step_reference(angle: int, x: int, y: int) -> Dict[str, int]:
    """One DDA micro-step, the plain-integer ground truth the cast cone is checked against."""
    dxm, dym = DIRX_MAG[angle], DIRY_MAG[angle]
    sx, sy = SIGNX[angle], SIGNY[angle]
    nx = (x - dxm) & 0xFF if sx else (x + dxm) & 0xFF
    ny = (y - dym) & 0xFF if sy else (y + dym) & 0xFF
    cx, cy = nx >> 4, ny >> 4
    pcx, pcy = x >> 4, y >> 4
    solid = MAP[cy * 16 + cx]
    crossed_x = cx != pcx
    crossed_y = cy != pcy
    if crossed_x and not crossed_y:
        frac = ny & 0x0F
    elif crossed_y and not crossed_x:
        frac = nx & 0x0F
    else:
        frac = (ny & 0x0F) if dxm >= dym else (nx & 0x0F)
    return {"nx": nx, "ny": ny, "solid": int(solid), "frac": frac}


def build_cast_step_cone_netlist() -> Netlist:
    """The DDA cast micro-step as a gate-level Netlist, lowering to {NOR, CONST0, CONST1}.

    Inputs (bit0 = LSB):
        angle[5]   the ray angle index 0..31
        x[8], y[8] the current ray position
    Outputs:
        nx0..nx7   advanced ray x
        ny0..ny7   advanced ray y
        solid      1 iff the new cell (nx>>4, ny>>4) is a wall
        frac0..3   the wall fraction at this step (only meaningful on a hit)

    The per-angle delta magnitudes and signs are hardwired ROMs (the trig landscape); the
    advance is the same +/- of a 0..3 magnitude on a byte; the map test is a 256-way ROM mux on
    the cell index; the frac pick is the oracle's face choice. Built only from NetlistBuilder
    emitters, so to_nor() lowers it to the buildable set. Checked exhaustively against
    cast_step_reference over every angle and the real DDA-reachable positions in the tests.
    """
    b = NetlistBuilder("cast_step")
    angle = _bus_in(b, "angle", 5)
    x = _bus_in(b, "x", 8)
    y = _bus_in(b, "y", 8)
    zero, one = b.const0(), b.const1()

    # per-angle trig ROMs.
    dirx = _rom(b, angle, list(DIRX_MAG), 2)           # |dx| 0..3
    diry = _rom(b, angle, list(DIRY_MAG), 2)           # |dy| 0..3
    signx = _rom(b, angle, list(SIGNX), 1)[0]
    signy = _rom(b, angle, list(SIGNY), 1)[0]

    dirx8 = list(dirx) + [zero] * 6
    diry8 = list(diry) + [zero] * 6

    # new_x = signx ? x - dirx : x + dirx, on a byte (x + ~dirx + 1 for subtract).
    add_x, _ = _ripple_add(b, x, dirx8, zero)
    not_dirx = [b.inv(t) for t in dirx8]
    sub_x, _ = _ripple_add(b, x, not_dirx, one)
    nx = _mux2(b, signx, add_x, sub_x)
    # new_y similarly.
    add_y, _ = _ripple_add(b, y, diry8, zero)
    not_diry = [b.inv(t) for t in diry8]
    sub_y, _ = _ripple_add(b, y, not_diry, one)
    ny = _mux2(b, signy, add_y, sub_y)

    # cell index = (ny>>4)*16 + (nx>>4) = {ny[4:8], nx[4:8]}; map ROM read.
    cx = nx[4:8]
    cy = ny[4:8]
    cell_idx = list(cx) + list(cy)                     # 8 bits, low nibble cx, high nibble cy
    solid = _rom(b, cell_idx, [int(v) for v in MAP], 1)[0]

    # frac pick: crossed_x = cx != prev_cx, crossed_y = cy != prev_cy.
    pcx = x[4:8]
    pcy = y[4:8]
    crossed_x = b.inv(_eq_bus(b, cx, pcx))
    crossed_y = b.inv(_eq_bus(b, cy, pcy))
    only_x = b.and_([crossed_x, b.inv(crossed_y)])
    only_y = b.and_([crossed_y, b.inv(crossed_x)])
    # dominant axis on a corner: dirx >= diry (unsigned 2-bit compare via x + ~y + 1 carry).
    not_diry2 = [b.inv(t) for t in diry]
    _d, ge = _ripple_add(b, dirx, not_diry2, one)      # carry == 1 means dirx >= diry
    nyf = ny[0:4]
    nxf = nx[0:4]
    # face select: only_x -> ny frac; only_y -> nx frac; else (corner) ge ? ny : nx.
    corner_frac = _mux2(b, ge, nxf, nyf)               # ge ? ny-frac : nx-frac
    frac = _mux2(b, only_x, _mux2(b, only_y, corner_frac, nxf), nyf)

    for i in range(8):
        b.alias_output(f"nx{i}", nx[i])
    for i in range(8):
        b.alias_output(f"ny{i}", ny[i])
    b.alias_output("solid", solid)
    for i in range(4):
        b.alias_output(f"frac{i}", frac[i])
    return b.finish()


# ---------------------------------------------------------------------------------
# A registered (DFF + NOR) sequential SLICE: the ray marcher for one column.
# ---------------------------------------------------------------------------------
#
# This is the sequential analogue of the cast cone: it wraps the per-step datapath in the
# ray-position (px, py) and step-counter registers and marches the DDA one micro-step per clock,
# latching the hit on the first solid cell. It is the inner loop of a frame (per-column cast), the
# part of the FSM that is genuinely SEQUENTIAL (state evolving over clocks), so it is the right
# piece to pin with sequential_equivalent over a frame's worth of steps.


# state-field bit widths for the march slice.
_PX_W = 8
_PY_W = 8
_STEP_W = 6                  # 0..STEPS
_HITD_W = 6                  # latched hit distance 0..STEPS
_HITF_W = 4                  # latched hit fraction
_DONE_W = 1                  # 1 once a wall was hit (march frozen)


def build_cast_march_netlist(angle: int) -> Netlist:
    """The single-column ray marcher as a gate + DFF Netlist for a FIXED angle.

    The angle is a hardwired constant (a column's angle is fixed for the cast), so the trig ROMs
    collapse to constants and the slice is a clean DDA loop over registers. State registers:
        px[8], py[8]   the marching ray position
        step[6]        the micro-step counter 0..STEPS
        done           1 once a wall is hit (march holds after the hit)
        hit_d[6]       latched hit distance (step at the hit)
        hit_f[4]       latched hit fraction
    Inputs:  clk, start (pulse to (re)seed the ray at the player position, step 0, done 0).
    Outputs: hit_d0..5, hit_f0..3, done, plus px/py/step exposed for the cross-check.

    On each clock while not done: advance the ray, test the map; on the first solid cell latch
    (hit_d = step+1, hit_f = frac) and set done. Proven sequential_equivalent to a behavioural
    Python march (cast_march_reference) over a full column of steps in the tests.
    """
    b = NetlistBuilder(f"cast_march_a{angle}")
    clk = b.declare_input("clk")
    start = b.declare_input("start")
    zero, one = b.const0(), b.const1()

    dxm, dym = DIRX_MAG[angle], DIRY_MAG[angle]
    sx, sy = SIGNX[angle], SIGNY[angle]

    # reserve register Q nets up front so the next-state logic can read them (feedback).
    px = [b.fresh_net() for _ in range(_PX_W)]
    py = [b.fresh_net() for _ in range(_PY_W)]
    step = [b.fresh_net() for _ in range(_STEP_W)]
    done = [b.fresh_net() for _ in range(_DONE_W)]
    hit_d = [b.fresh_net() for _ in range(_HITD_W)]
    hit_f = [b.fresh_net() for _ in range(_HITF_W)]

    dxm8 = _const_bits(b, dxm, 8)
    dym8 = _const_bits(b, dym, 8)

    # advance the ray one step (constant magnitudes, constant sign -> a pure add or subtract).
    if sx:
        not_dx = [b.inv(t) for t in dxm8]
        nx, _ = _ripple_add(b, px, not_dx, one)
    else:
        nx, _ = _ripple_add(b, px, dxm8, zero)
    if sy:
        not_dy = [b.inv(t) for t in dym8]
        ny, _ = _ripple_add(b, py, not_dy, one)
    else:
        ny, _ = _ripple_add(b, py, dym8, zero)

    # map test on the new cell.
    cell_idx = list(nx[4:8]) + list(ny[4:8])
    solid = _rom(b, cell_idx, [int(v) for v in MAP], 1)[0]

    # frac pick (same face logic as the cone), constants for the magnitudes.
    pcx, pcy = px[4:8], py[4:8]
    cx, cy = nx[4:8], ny[4:8]
    crossed_x = b.inv(_eq_bus(b, cx, pcx))
    crossed_y = b.inv(_eq_bus(b, cy, pcy))
    only_x = b.and_([crossed_x, b.inv(crossed_y)])
    only_y = b.and_([crossed_y, b.inv(crossed_x)])
    nyf, nxf = ny[0:4], nx[0:4]
    # dominant axis is a compile-time constant here (dxm >= dym).
    corner_frac = nyf if dxm >= dym else nxf
    frac = _mux2(b, only_x, _mux2(b, only_y, corner_frac, nxf), nyf)

    # step + 1, and the hit detect (solid and not already done).
    step_p1, _ = _ripple_add(b, step, _const_bits(b, 1, _STEP_W), zero)
    not_done = b.inv(done[0])
    # also stop at STEPS (the oracle's max range): last_step = (step == STEPS-1).
    last_step = _eq_const(b, step, STEPS - 1)
    hit_now = b.and_([not_done, b.or_([solid, last_step])])
    marching = b.and_([not_done, b.inv(hit_now)])      # advance only while not hit and not done
    # the latched fraction is the face frac on a real solid hit, but 0 on a max-range stop with
    # no wall (matches _cast_hw's `return STEPS, 0` and RaycasterFsm's Mux(solid, frac_pick, 0)).
    frac = _mux2(b, solid, _const_bits(b, 0, _HITF_W), frac)

    # -- next-state, gated by start / marching --
    # start: px<-PLAYER_X, py<-PLAYER_Y, step<-0, done<-0.
    # else marching: px<-nx, py<-ny, step<-step+1.
    # else hit_now: latch hit_d/hit_f, done<-1.
    # else hold.
    px_seed = _const_bits(b, PLAYER_X, _PX_W)
    py_seed = _const_bits(b, PLAYER_Y, _PY_W)

    px_next = _mux2(b, start, _mux2(b, marching, list(px), nx), px_seed)
    py_next = _mux2(b, start, _mux2(b, marching, list(py), ny), py_seed)
    step_next = _mux2(b, start, _mux2(b, marching, list(step), step_p1),
                      _const_bits(b, 0, _STEP_W))
    # done: set on a hit, cleared on start, else hold.
    done_set = b.or_([done[0], hit_now])
    done_next = _mux2_bit(b, start, done_set, zero)
    # hit_d / hit_f: capture step+1 / frac on the hit cycle, cleared on start, else hold.
    hitd_cap = _mux2(b, hit_now, list(hit_d), step_p1[:_HITD_W])
    hitd_next = _mux2(b, start, hitd_cap, _const_bits(b, 0, _HITD_W))
    hitf_cap = _mux2(b, hit_now, list(hit_f), list(frac))
    hitf_next = _mux2(b, start, hitf_cap, _const_bits(b, 0, _HITF_W))

    for i in range(_PX_W):
        b.dff_into(px_next[i], clk, px[i])
    for i in range(_PY_W):
        b.dff_into(py_next[i], clk, py[i])
    for i in range(_STEP_W):
        b.dff_into(step_next[i], clk, step[i])
    b.dff_into(done_next, clk, done[0])
    for i in range(_HITD_W):
        b.dff_into(hitd_next[i], clk, hit_d[i])
    for i in range(_HITF_W):
        b.dff_into(hitf_next[i], clk, hit_f[i])

    for i in range(_HITD_W):
        b.alias_output(f"hit_d{i}", hit_d[i])
    for i in range(_HITF_W):
        b.alias_output(f"hit_f{i}", hit_f[i])
    b.alias_output("done", done[0])
    for i in range(_PX_W):
        b.alias_output(f"px{i}", px[i])
    for i in range(_PY_W):
        b.alias_output(f"py{i}", py[i])
    for i in range(_STEP_W):
        b.alias_output(f"step{i}", step[i])
    return b.finish()


def cast_march_reference(angle: int, steps: int) -> List[Dict[str, int]]:
    """Behavioural cycle model of the marcher: per-cycle (done, hit_d, hit_f) after a start.

    Cycle 0 is the start (seed). Then one DDA micro-step per cycle until a wall is hit (or STEPS),
    after which the march holds done=1 with the latched hit. This is the ground truth the
    registered netlist is checked against with sequential_equivalent.
    """
    out: List[Dict[str, int]] = []
    px, py = PLAYER_X, PLAYER_Y
    step = 0
    done = 0
    hit_d = 0
    hit_f = 0
    dxm, dym = DIRX_MAG[angle], DIRY_MAG[angle]
    sx, sy = SIGNX[angle], SIGNY[angle]
    for cyc in range(steps):
        if cyc == 0:
            # the start cycle: registers seed, no advance yet (matches the start mux).
            px, py, step, done, hit_d, hit_f = PLAYER_X, PLAYER_Y, 0, 0, 0, 0
        elif not done:
            pcx, pcy = px >> 4, py >> 4
            nx = (px - dxm) & 0xFF if sx else (px + dxm) & 0xFF
            ny = (py - dym) & 0xFF if sy else (py + dym) & 0xFF
            cx, cy = nx >> 4, ny >> 4
            solid = MAP[cy * 16 + cx]
            last_step = (step == STEPS - 1)
            if solid or last_step:
                # hit this cycle: latch, set done, do NOT advance the position registers.
                if not solid:
                    # max-range stop with no wall: frac is 0 (matches _cast_hw return STEPS, 0).
                    frac = 0
                else:
                    crossed_x = cx != pcx
                    crossed_y = cy != pcy
                    if crossed_x and not crossed_y:
                        frac = ny & 0x0F
                    elif crossed_y and not crossed_x:
                        frac = nx & 0x0F
                    else:
                        frac = (ny & 0x0F) if dxm >= dym else (nx & 0x0F)
                hit_d = (step + 1) & ((1 << _HITD_W) - 1)
                hit_f = frac
                done = 1
            else:
                px, py, step = nx, ny, step + 1
        out.append({"done": done, **{f"hit_d{i}": (hit_d >> i) & 1 for i in range(_HITD_W)},
                    **{f"hit_f{i}": (hit_f >> i) & 1 for i in range(_HITF_W)}})
    return out


def march_output_trace(netlist: Netlist, angle: int, steps: int) -> List[Dict[str, int]]:
    """Step the registered marcher: cycle 0 pulses start, then steps-1 march cycles."""
    sim = SeqSim(netlist)
    sim.reset({"clk": 0, "start": 0})
    out: List[Dict[str, int]] = []
    for cyc in range(steps):
        sim.clock_cycle({"start": 1 if cyc == 0 else 0}, clock="clk")
        row = {"done": sim.value("done")}
        for i in range(_HITD_W):
            row[f"hit_d{i}"] = sim.value(f"hit_d{i}")
        for i in range(_HITF_W):
            row[f"hit_f{i}"] = sim.value(f"hit_f{i}")
        out.append(row)
    return out


# ---------------------------------------------------------------------------------
# Representative ROUTABLE slices that close 100 percent DRC-clean.
# ---------------------------------------------------------------------------------
#
# The slices below are the small, fast representative pieces of the cast datapath the tests route.
# They predate the router fix that made the LARGE cones route clean too:
#   - the full per-step cast cone lowers to ~3349 NOR (dominated by the 256-way map ROM),
#   - the per-pixel paint cone to ~1419 NOR,
#   - the per-column shade cone to ~1802 NOR.
# All of these now route 100 percent of nets DRC-clean through the shared router (the wide-fan-in
# footprint/coalesce + output-pad-channel fixes removed the old STUCK.md #8 route_short / route_cuts
# _pad fallback). The 92-cell adder, the 893-cell ALU and the 1631-cell CPU also route 0-DRC, so the
# backend is no longer scale-limited at this size. The slices remain because they are cheap to route
# in the test loop and exercise both the combinational and sequential backends on real cast values:
#   COMBINATIONAL: build_cast_advance_cone_netlist (the dual-axis DDA ray advance + face frac for
#                  one column), ~344 NOR, the heart of the per-step cast, routes 0-DRC.
#   SEQUENTIAL:    build_dist_pipeline_netlist (a clocked 6-bit hit-distance delay line), register
#                  tiles + the clock spine, routes 0-DRC, exercising the sequential backend.


def build_cast_advance_cone_netlist(angle: int = 12, with_frac: bool = False) -> Netlist:
    """The dual-axis DDA ray ADVANCE (and optionally the face-fraction) for a fixed column angle,
    as a buildable {NOR, CONST0, CONST1} Netlist. This is the per-step cast datapath WITHOUT the
    256-way map ROM, a small fast slice that routes 100 percent DRC-clean.

    Inputs:  x[8], y[8]  the ray position.
    Outputs: nx0..7, ny0..7  the advanced position; with_frac adds frac0..3 (the wall fraction).

    The advance is the same +/- of the per-angle constant magnitude the FSM uses each micro-step
    (the genuine per-step ray-position update of the DDA march); the frac pick is the oracle's face
    choice. Checked against cast_step_reference (the nx/ny[/frac] fields) for this angle over the
    real DDA trajectory in the tests. Both the advance-only and the with_frac forms route DRC-clean
    (the with_frac form's extra output pads used to trip the old edge-pad fallback; the router now
    reserves an output-pad channel, so it is clean too).
    """
    b = NetlistBuilder(f"cast_advance_a{angle}" + ("_f" if with_frac else ""))
    x = _bus_in(b, "x", 8)
    y = _bus_in(b, "y", 8)
    zero, one = b.const0(), b.const1()
    dxm, dym = DIRX_MAG[angle], DIRY_MAG[angle]
    sx, sy = SIGNX[angle], SIGNY[angle]
    dxm8 = _const_bits(b, dxm, 8)
    dym8 = _const_bits(b, dym, 8)
    if sx:
        nx, _ = _ripple_add(b, x, [b.inv(t) for t in dxm8], one)
    else:
        nx, _ = _ripple_add(b, x, dxm8, zero)
    if sy:
        ny, _ = _ripple_add(b, y, [b.inv(t) for t in dym8], one)
    else:
        ny, _ = _ripple_add(b, y, dym8, zero)
    for i in range(8):
        b.alias_output(f"nx{i}", nx[i])
    for i in range(8):
        b.alias_output(f"ny{i}", ny[i])
    if with_frac:
        cx, cy = nx[4:8], ny[4:8]
        pcx, pcy = x[4:8], y[4:8]
        crossed_x = b.inv(_eq_bus(b, cx, pcx))
        crossed_y = b.inv(_eq_bus(b, cy, pcy))
        only_x = b.and_([crossed_x, b.inv(crossed_y)])
        only_y = b.and_([crossed_y, b.inv(crossed_x)])
        nyf, nxf = ny[0:4], nx[0:4]
        corner = nyf if dxm >= dym else nxf
        frac = _mux2(b, only_x, _mux2(b, only_y, corner, nxf), nyf)
        for i in range(4):
            b.alias_output(f"frac{i}", frac[i])
    return b.finish()


def build_col_shade_cone_netlist() -> Netlist:
    """The per-column slice-geometry + wall-shade datapath as a buildable {NOR,...} Netlist.

    Inputs (bit0 = LSB):
        dist[6]    the hit distance (DDA hit step) 1..STEPS
        frac[4]    the wall fraction at the hit
        tex        texture-enable
    Outputs:
        top0..5    slice top row    = (H - RECIP[dist]) // 2
        bot0..5    slice bottom row = top + RECIP[dist]
        shade0..4  wall shade       = HW_STEP_SHADE[dist], +HW_WALL_TEX[frac] clamped 2..16 if tex

    This is exactly the per-column geometry block of RaycasterFsm (the recip / stepshade / walltex
    ROMs and the clamp), pulled out as a standalone combinational cone. Small (the ROMs are 6-bit
    indexed), so it places + channel-routes 100 percent DRC-clean like the adder. Checked against
    raycaster_fsm._slice_top_bot / _wall_shade exactly in the tests.
    """
    b = NetlistBuilder("col_shade")
    dist = _bus_in(b, "dist", 6)
    frac = _bus_in(b, "frac", 4)
    tex = b.declare_input("tex")
    zero, one = b.const0(), b.const1()

    # line_h = RECIP[dist]; on the lo panel RECIP maxes at H, so no clamp is needed.
    line_h = _rom(b, dist, list(F.RECIP), 6)
    H = F.H
    line_h7 = list(line_h) + [zero]                    # widen to 7 bits

    # top = (H - line_h) >> 1.  H - line_h via H + ~line_h + 1.
    h_const = _const_bits(b, H, 7)
    not_lh = [b.inv(t) for t in line_h7]
    h_minus, _ = _ripple_add(b, h_const, not_lh, one)
    top6 = h_minus[1:7]                                # >>1, take bits 1..6 (6-bit top 0..16)

    # bot = top + line_h (both <= H == 32, fits 6 bits).
    bot7, _ = _ripple_add(b, list(top6), line_h7[:6], zero)
    bot6 = bot7[:6]

    # base shade = HW_STEP_SHADE[dist]; texture bias = signed HW_WALL_TEX[frac].
    base = _rom(b, dist, list(F.HW_STEP_SHADE), 5)
    texb = _rom(b, frac, [v & 0x1F for v in F.HW_WALL_TEX], 5)   # 5-bit two's complement bias
    # shade_raw = base + sign_extend(texb), a 7-bit signed add.
    base7 = list(base) + [zero, zero]
    texb7 = list(texb) + [texb[4], texb[4]]            # sign-extend the 5-bit bias to 7
    sraw, _ = _ripple_add(b, base7, texb7, zero)
    sraw_sign = sraw[6]
    # clamp to [2, 16]: if sraw < 2 -> 2; if sraw > 16 -> 16.
    # sraw < 2  iff negative OR (sraw == 0 or sraw == 1).
    lt2 = b.or_([sraw_sign, _eq_const(b, sraw, 0), _eq_const(b, sraw, 1)])
    # sraw > 16 iff not negative and (sraw - 16) > 0, i.e. sraw >= 17.
    not_17 = [b.inv(t) for t in _const_bits(b, 17, 7)]
    _d, ge17 = _ripple_add(b, sraw, not_17, one)        # carry == 1 iff sraw >= 17
    gt16 = b.and_([b.inv(sraw_sign), ge17])
    clamped = _mux2(b, lt2, _mux2(b, gt16, sraw[:5], _const_bits(b, 16, 5)),
                    _const_bits(b, 2, 5))
    shade = _mux2(b, tex, list(base), clamped)

    for i in range(6):
        b.alias_output(f"top{i}", top6[i])
    for i in range(6):
        b.alias_output(f"bot{i}", bot6[i])
    for i in range(5):
        b.alias_output(f"shade{i}", shade[i])
    return b.finish()


def build_route_slice(angle: int = 12) -> Netlist:
    """The representative COMBINATIONAL slice that routes 100 percent DRC-clean: the dual-axis DDA
    advance + frac cone for one column, lowered to {NOR, CONST0, CONST1}. Real cast datapath, small
    enough to place + channel-route DRC-clean like the 4-bit adder and the ALU."""
    return build_cast_advance_cone_netlist(angle).to_nor()


def build_dist_pipeline_netlist(stages: int = 4) -> Netlist:
    """A small SEQUENTIAL routable slice: a clocked 6-bit hit-distance delay line.

    This exercises the register-tile + clock-spine backend (the same path the 3-bit counter /
    shift register / CPU use) on the raycaster's own datapath value, the per-column hit distance,
    at a size that routes DRC-clean. `stages` 6-bit registers form a delay line (a column-pipeline
    latency); only the LAST stage is exposed as a port (intermediate stages stay internal), which
    keeps the output-pad count low so the shared router stays DRC-clean. The point is a clocked
    raycaster-distance slice that places with register tiles and a reaching clock, routed 100
    percent DRC-clean, complementing the (proven, but large) full registered marcher.
    """
    b = NetlistBuilder(f"dist_pipe{stages}")
    clk = b.declare_input("clk")
    din = _bus_in(b, "dist", 6)
    prev = din
    for s in range(stages):
        q = [b.dff(prev[i], clk) for i in range(6)]
        prev = q
    for i in range(6):
        b.alias_output(f"dout{i}", prev[i])              # only the final stage is a port
    return b.finish()


def dist_pipeline_reference(stages: int, trace: List[int]) -> List[int]:
    """Behavioural model of the distance delay line under the SeqSim clock_cycle convention.

    clock_cycle applies the data then pulses the rising edge in one cycle, so the value captured
    by the first DFF is visible at that DFF's Q the SAME cycle and propagates one stage per cycle
    thereafter; an n-stage chain therefore shows (n-1)-cycle visible latency (out[k] = din[k-(n-1)],
    0 before), exactly what simulate_trace() reports for both the behavioural and lowered forms.
    """
    out: List[int] = []
    latency = max(0, stages - 1)
    for k in range(len(trace)):
        out.append(trace[k - latency] & 0x3F if k - latency >= 0 else 0)
    return out


def build_seq_route_slice(stages: int = 4) -> Netlist:
    """The sequential routable slice (the distance pipeline), kept-register lowered for routing."""
    return build_dist_pipeline_netlist(stages).to_nor(keep_registers=True)


# ---------------------------------------------------------------------------------
# Reporting: the metrics the brief asks for.
# ---------------------------------------------------------------------------------

def fsm_metrics() -> Dict[str, int]:
    """Whole-FSM metrics (counts and budgets), independent of routing."""
    reg = F.fsm_register_bits()
    paint_low = build_paint_cone_netlist().to_nor()
    cast_low = build_cast_step_cone_netlist().to_nor()
    shade_low = build_col_shade_cone_netlist().to_nor()
    return {
        "control_register_bits": reg["_control_total"],
        "framebuffer_bits": reg["_framebuffer"],
        "paint_cone_NOR": paint_low.stats().get("NOR", 0),
        "cast_cone_NOR": cast_low.stats().get("NOR", 0),
        "shade_cone_NOR": shade_low.stats().get("NOR", 0),
    }


def cycles_per_frame(heading: int = 0) -> int:
    """Cycles the behavioural RaycasterFsm takes to render one frame at `heading` (by simulation).

    Reuses the test harness's run loop indirectly: instantiate, pulse start, count edges to done.
    """
    from amaranth.hdl import Module
    from amaranth.sim import Simulator
    from raycaster_fsm import RaycasterFsm

    dut = RaycasterFsm()
    m = Module()
    m.submodules.dut = dut
    out = {}

    async def tb(ctx):
        ctx.set(dut.heading, heading)
        ctx.set(dut.texture, 1)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)
        cyc = 0
        while not ctx.get(dut.done) and cyc < 100000:
            await ctx.tick()
            cyc += 1
        out["cyc"] = cyc

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(tb)
    sim.run()
    return out["cyc"]


def route_slice_report(netlist: Netlist) -> Dict[str, object]:
    """Place + channel-route `netlist`, returning the routing/DRC metrics for the report."""
    from emit import build_scenario
    from check import drc, unrouted_nets, overlap_violations
    from collections import Counter

    scen, rr = build_scenario(netlist)
    routed, total = rr.coverage()
    d = drc(scen)
    bridges = sum(len(r.bridges) for r in scen.routes)
    regs = [c for c in scen.cells if c.is_register()]
    return {
        "cells": len(scen.cells),
        "register_tiles": len(regs),
        "routed": routed,
        "total_nets": total,
        "overlaps": len(overlap_violations(scen)),
        "unrouted": len(unrouted_nets(scen)),
        "drc_violations": len(d),
        "drc_kinds": dict(Counter(v.kind for v in d)),
        "bridges": bridges,
        "map": (scen.map_x, scen.map_y),
        "scenario": scen,
        "route_result": rr,
    }


def emit_and_reconstruct_slice(netlist: Netlist, samples: int = 2000) -> Dict[str, object]:
    """Emit `netlist`'s Scenario + .nut, reconstruct from the placement, and check equivalence.

    The end-to-end backend close for a combinational slice: place + route, serialise to the
    Scenario JSON and the GameScript .nut, then read the connectivity back off the placed pins
    and routes (scenario_to_netlist) and prove the reconstruction computes the SAME function as the
    source. Returns the scenario, the .nut text, the reconstructed netlist, and the verdict.

    Equivalence is checked by FUNCTIONAL SAMPLING, not a full truth table: the advance cone has 16
    primary inputs (x[8], y[8]), so an exhaustive 2^16 truth_table() is wasteful. We instead drive
    the source and the reconstruction with the SAME inputs over the real DDA trajectory (the
    positions the ray actually visits) plus a block of random inputs, and assert their outputs
    agree on every sample. This is the same strong-sample equivalence hdl/test_cpu.py uses for its
    wide combinational cone (the 55-input CPU cone), and it catches a mis-route the same way.
    """
    import random

    from emit import build_scenario
    from check import scenario_to_netlist

    scen, rr = build_scenario(netlist)
    nut = scen.to_nut()
    rebuilt = scenario_to_netlist(scen, require_routed=True)

    if set(netlist.ports.inputs) != set(rebuilt.ports.inputs) or \
            set(netlist.ports.outputs) != set(rebuilt.ports.outputs):
        return {"scenario": scen, "nut": nut, "rebuilt": rebuilt, "equivalent": False,
                "route_result": rr}

    ins = list(netlist.ports.inputs)
    rng = random.Random(20260620)
    eq = True
    # the real DDA trajectory for a few angles (the inputs the ray actually presents), then random.
    cases: List[Dict[str, int]] = []
    if {"x0", "y0"} <= set(ins):
        for angle in (0, 7, 12, 24):
            px, py = PLAYER_X, PLAYER_Y
            for _ in range(STEPS):
                iv = {f"x{i}": (px >> i) & 1 for i in range(8)}
                iv.update({f"y{i}": (py >> i) & 1 for i in range(8)})
                iv.update({n: rng.randint(0, 1) for n in ins if n not in iv})
                cases.append(iv)
                r = cast_step_reference(angle, px, py)
                if r["solid"]:
                    break
                px, py = r["nx"], r["ny"]
    for _ in range(samples):
        cases.append({n: rng.randint(0, 1) for n in ins})
    for iv in cases:
        if netlist.outputs_for(iv) != rebuilt.outputs_for(iv):
            eq = False
            break

    return {"scenario": scen, "nut": nut, "rebuilt": rebuilt, "equivalent": eq,
            "route_result": rr}


def frame_pipeline_report(route_clean: bool = True) -> Dict[str, object]:
    """The full report the brief asks for: whole-FSM metrics PLUS the routed representative slice.

    `route_clean` True routes the small DRC-clean slices (the dual-axis advance cone and the
    distance pipeline); the large cones (cast / paint / shade) are reported by NOR count only here
    to keep the report fast, but they now also route 0-DRC through the shared router (the
    wide-fan-in and output-pad-channel fixes removed the old STUCK.md #8 route_short fallback).
    """
    report: Dict[str, object] = {"fsm": fsm_metrics()}
    if route_clean:
        report["advance_slice"] = {
            k: v for k, v in route_slice_report(build_route_slice()).items()
            if k not in ("scenario", "route_result")
        }
        report["dist_pipeline_slice"] = {
            k: v for k, v in route_slice_report(build_seq_route_slice(4)).items()
            if k not in ("scenario", "route_result")
        }
    return report
