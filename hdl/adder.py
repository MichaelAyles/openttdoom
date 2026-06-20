"""The 4-bit ripple-carry adder, the M4 de-risking target.

Three views of the same circuit:

  1. Adder4: a behavioural Amaranth module, a + b + cin. This is the golden reference,
     simulated with amaranth.sim.Simulator in the tests.

  2. build_adder4_netlist(): a STRUCTURAL gate-level ripple-carry adder built by hand from
     four full adders using the NetlistBuilder from netlist.py. This is the verified
     synthesis path. It is exact, exhaustively checked against the reference, and lowers
     cleanly to the buildable {NOR, CONST0, CONST1} set via .to_nor().

  3. synth_adder4_via_yosys(): an OPTIONAL cross-check that drives a real yosys (the WASM
     yosys bundled with amaranth-yosys) over amaranth RTLIL to produce a gate-level netlist,
     which we import and compare to the structural build. See the note in that function for
     why yosys does the gate decomposition but not the final NOR techmap.

Full adder used throughout:
    sum  = a ^ b ^ cin
    cout = (a & b) | (cin & (a ^ b))

Ports of the netlist:
    inputs  : a0 a1 a2 a3 b0 b1 b2 b3 cin   (bit 0 == least significant)
    outputs : s0 s1 s2 s3 cout
"""

from __future__ import annotations

from amaranth.hdl import Cat, Elaboratable, Module, Signal

from netlist import Netlist, NetlistBuilder


# --- view 1: behavioural golden reference ----------------------------------------

class Adder4(Elaboratable):
    """4-bit adder with carry in and carry out. s = (a + b + cin) mod 16, cout = carry."""

    def __init__(self):
        self.a = Signal(4)
        self.b = Signal(4)
        self.cin = Signal()
        self.s = Signal(4)
        self.cout = Signal()

    def elaborate(self, platform):
        m = Module()
        total = self.a + self.b + self.cin   # 5-bit result
        m.d.comb += self.s.eq(total[:4])
        m.d.comb += self.cout.eq(total[4])
        return m


# --- view 2: structural gate-level netlist (the verified synth path) --------------

def build_adder4_netlist() -> Netlist:
    """Build the ripple-carry adder as a gate-level Netlist from four full adders.

    Uses the high level gate emitters on NetlistBuilder (xor2, and_, or_). Those emit
    NOR cells directly, so the structural netlist is already buildable (82 NOR cells), but
    we keep the gate structure readable here. to_nor() on the result is NOT a no-op: it
    performs a genuine re-lowering, walking the driver graph via driver_of() and re-expanding
    every gate from scratch, which changes the NOR count from 82 to 92. The tests therefore
    exercise a real lowering pass and confirm the result stays equivalent and buildable.
    """
    b = NetlistBuilder("adder4")

    a = [b.declare_input(f"a{i}") for i in range(4)]
    bb = [b.declare_input(f"b{i}") for i in range(4)]
    cin = b.declare_input("cin")

    carry = cin
    for i in range(4):
        ai, bi = a[i], bb[i]
        axb = b.xor2(ai, bi)                 # a ^ b
        s_i = b.xor2(axb, carry)             # (a ^ b) ^ cin
        ab = b.and_([ai, bi])                # a & b
        cc = b.and_([carry, axb])            # cin & (a ^ b)
        carry = b.or_([ab, cc])              # cout = (a & b) | (cin & (a ^ b))
        b.alias_output(f"s{i}", s_i)
    b.alias_output("cout", carry)

    return b.finish()


# --- view 3: optional real-yosys cross-check --------------------------------------

def _adder4_amaranth_structural():
    """A bit-level structural adder in Amaranth, no $add cell.

    We spell out the full adders so that after yosys simplemap we get $_XOR_/$_AND_/$_OR_
    gate cells rather than a coarse $add macro. The stripped WASM yosys has no techmap or
    abc to break $add apart, so this bit-level form is what lets a real yosys produce a
    gate-level netlist for the cross-check.
    """
    m = Module()
    a = Signal(4)
    b = Signal(4)
    cin = Signal()
    s = Signal(4)
    cout = Signal()

    carry = cin
    souts = []
    for i in range(4):
        ai, bi = a[i], b[i]
        axb = ai ^ bi
        souts.append(axb ^ carry)
        carry = (ai & bi) | (carry & axb)
    m.d.comb += s.eq(Cat(*souts))
    m.d.comb += cout.eq(carry)
    return m, [a, b, cin, s, cout]


def synth_adder4_via_yosys() -> Netlist:
    """Run a real yosys over amaranth RTLIL and import the gate-level result as a Netlist.

    This proves the toolchain reaches an actual synthesizer. yosys does the real work of
    flattening, optimizing, and lowering to single-bit gate cells ($_XOR_/$_AND_/$_OR_).

    What yosys does NOT do here: the final techmap to a NOR-only cell library. The yosys
    build bundled with amaranth-yosys is a stripped WASM build with no read_verilog, no
    techmap, and no abc, so the classic `abc -liberty nor.lib` mapping is unavailable. The
    NOR lowering therefore stays in Python via Netlist.to_nor(), which is exact and
    exhaustively verified. The proper full-yosys NOR techmap is parked in synth/adder4.ys
    as a TODO(human) for an environment with a complete yosys install.

    Raises RuntimeError if no yosys is reachable, so callers can treat it as optional.
    """
    import json

    try:
        from amaranth.back import rtlil
        from amaranth._toolchain.yosys import find_yosys
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"amaranth yosys toolchain unavailable: {exc}")

    try:
        yosys = find_yosys(lambda ver: ver >= (0, 10))
    except Exception as exc:
        raise RuntimeError(f"no usable yosys binary: {exc}")

    m, ports = _adder4_amaranth_structural()
    il = rtlil.convert(m, ports=ports)

    script = [
        f"read_rtlil <<rtlil\n{il}\nrtlil",
        "hierarchy -auto-top",
        "proc",
        "flatten",
        "opt",
        "simplemap",   # lower coarse cells to single-bit $_XOR_/$_AND_/$_OR_/$_NOT_
        "opt",
        "write_json",  # to stdout
    ]
    out = yosys.run(["-q", "-"], stdin="\n".join(script), ignore_warnings=True)
    doc = json.loads(out[out.index("{"):])
    return _import_yosys_json(doc)


# yosys gate cell type -> (CELL_LIBRARY type, ordered input port names)
_YOSYS_GATE_MAP = {
    "$_NOT_": ("NOT", ["A"]),
    "$_BUF_": ("BUF", ["A"]),
    "$_AND_": ("AND", ["A", "B"]),
    "$_OR_": ("OR", ["A", "B"]),
    "$_XOR_": ("XOR", ["A", "B"]),
    "$_XNOR_": ("XNOR", ["A", "B"]),
    "$_NAND_": ("NAND", ["A", "B"]),
    "$_NOR_": ("NOR", ["A", "B"]),
}


def _import_yosys_json(doc: dict) -> Netlist:
    """Turn a yosys write_json gate-level netlist into our Netlist.

    Only the gate cells in _YOSYS_GATE_MAP are understood. A bit number from yosys becomes
    a net name like nNN. Module ports keep their declared names (a, b, s are buses, so they
    expand to a0..a3 etc to match the structural build's port names).
    """
    from netlist import Cell, Ports

    mods = list(doc["modules"].keys())
    top = doc["modules"][mods[0]]

    def netname(bit) -> str:
        if isinstance(bit, str):           # constants "0"/"1"/"x"
            return {"0": "__const0", "1": "__const1"}.get(bit, f"__{bit}")
        return f"n{bit}"

    # map module port bits to friendly names, expanding buses to name<i>.
    bit_alias: dict[str, str] = {}
    inputs: list[str] = []
    outputs: list[str] = []
    for pname, pinfo in top["ports"].items():
        bits = pinfo["bits"]
        direction = pinfo["direction"]
        for i, bit in enumerate(bits):
            friendly = pname if len(bits) == 1 else f"{pname}{i}"
            bit_alias[netname(bit)] = friendly
            if direction == "input":
                inputs.append(friendly)
            elif direction == "output":
                outputs.append(friendly)

    def resolve(bit) -> str:
        raw = netname(bit)
        return bit_alias.get(raw, raw)

    cells: list[Cell] = []
    cid = 0
    seen_const: dict[str, str] = {}
    for cname, cinfo in top["cells"].items():
        ctype = cinfo["type"]
        if ctype not in _YOSYS_GATE_MAP:
            raise ValueError(f"unmapped yosys cell type {ctype}")
        lib_type, in_ports = _YOSYS_GATE_MAP[ctype]
        conns = cinfo["connections"]
        ins = [resolve(conns[p][0]) for p in in_ports]
        out = resolve(conns["Y"][0])
        cells.append(Cell(f"y{cid}", lib_type, ins, out))
        cid += 1

    # if any const nets were referenced, tie them off.
    const_nets = set()
    for c in cells:
        for n in c.inputs:
            if n in ("__const0", "__const1"):
                const_nets.add(n)
    for n in sorted(const_nets):
        if n == "__const0":
            cells.insert(0, Cell("yc0", "CONST0", [], "__const0"))
        else:
            cells.insert(0, Cell("yc1", "CONST1", [], "__const1"))

    nl = Netlist("adder4_yosys", cells, Ports(inputs, outputs))
    nl.validate()
    return nl
