# openttdoom gate design (M2)

This is the dev log for the M2 piece: how a single logic gate is meant to be
realised out of OpenTTD track, signals and a clock train, and how we choose to
build it on the map. It is a design and research note, not a claim that any of
this is verified in game yet. The honest status of what is and is not proven is
at the bottom and in STUCK.md.

No em-dashes in here on purpose, to match the owner's style.

## What we are building

The substrate rule, fixed by the brief and by synth/netlist.py, is:

- A net is one bit.
- Train presence encodes the bit. A train sitting on the net's track at the
  sampling moment means 1, an empty track means 0.
- The only gate we physically build is NOR. NOT is a one input NOR, so it is the
  same tile. CONST0 and CONST1 are hardwired track, not gates.
- The design is synchronous. A train running a fixed loop is the clock. Once per
  lap it produces a clock edge, and on that edge every gate samples its inputs
  and the result appears one edge later. That one edge of latency is the
  register behaviour, and it is what scenarios/gate_model.py models and tests.

NOR is universal, so once we have a working clocked NOR tile and a way to route
nets between tiles, we can build anything the synthesiser hands us.

## How signals make logic possible

OpenTTD signals already compute boolean functions of track occupancy. We are not
inventing logic, we are wiring up logic the game engine evaluates for us every
tick. The relevant pieces:

- Block (normal) signal. Green when the next block is empty, red when any train
  is in it. So a signal is literally a sensor for "is this block occupied", which
  is "is this bit 1".
- Two way signal. A signal you can read from behind. The back face shows red when
  the block on the train's side is occupied. This is the key negation primitive:
  it lets a downstream signal detect an upstream train, which is how you read a
  bit without consuming it.
- Pre-signals: entry, exit, combo. An entry or combo signal looks ahead at all
  the exit and combo signals in the block in front of it. It goes green if at
  least one of them is green, and red only if every one of them is red. That is a
  ready made boolean gate over "block free" conditions:
  - entry/combo red iff all downstream exits red. That is an AND over the
    occupancy bits (all paths blocked).
  - because a single green downstream forces the entry green, the same structure
    read the other way is an OR over "some path free".
- Path (PBS) signals reserve a whole path rather than a block. We mostly avoid
  them for gate internals because we want the simple, well defined block
  occupancy semantics, but the clock loop and the longer routing runs can use
  one way PBS to keep trains moving in one direction.

Quoting the OpenTTD manual and junctionary for the two facts the gate leans on:
an entry pre-signal "checks the signal aspect of all exit pre-signals of the
signal block following the entry pre-signal", and for negation "we simply make
signal 2 a bi-directional exit signal. Then if there is a train in the block
before it ... the back of the signal will show red." Sources at the end.

## Two encodings of a bit, and why we pick presence

The classic zem.fi construction uses a two track encoding: one track means 0, the
other means 1, value undefined if both or neither are occupied. That is robust
but doubles the track and needs a release path to clear the old value when the
input changes. The openttdcoop optimised gates instead lean on a clock train and
single track presence, sampled at a known moment, which is far more compact.

We go with single track presence sampled at the clock edge, because:

- it matches synth/netlist.py exactly ("a net's value is encoded by train
  presence sampled at a clock edge: train present == 1"),
- it halves the track per net,
- it gives every gate the same one edge register latency, which makes a long
  chain settle predictably instead of racing. That predictable latency is the
  whole reason the design is clocked and is what gate_model.py pins down.

The cost is that single track presence needs a disciplined clock so every gate
samples at the same moment. That is the clock train's job.

## The clocked NOR tile, intended construction

Intended, not yet verified in game. The pieces:

1. Input taps. Each input net arrives as a piece of track that may or may not
   hold a train at the clock edge. We read it with a two way signal so reading
   does not consume the train.
2. The NOR evaluation. NOR(a, b, ...) is 1 only when no input is present. A
   combo or entry signal that looks at the exit signals of all the input blocks
   is red iff all inputs are present, and green iff at least one input is
   present. Feed that aspect into the output stage so the output track gets a
   train exactly when every input was absent. That is NOR.
3. The output register. The output track holds a train (or not) and is itself
   read by the next tile at the following edge. Holding the value for a full
   clock period is what gives the one edge latency.
4. The clock gating. A pulse derived from the clock train releases the sampling
   train(s) at the edge, so all tiles sample together. Between edges the inputs
   can change without disturbing the latched output.

A NOT tile is the same thing with one input.

### Why this is the hard part

The logic above is sound at the signal level. The unsolved engineering is the
exact tile by tile track layout, signal placement and the clock release timing
that makes one physical tile do this reliably and compose with its neighbours
through the routed nets. The reference gates exist as screenshots and old saves,
not as coordinates, and several depend on pathfinder behaviour (the zem.fi NOR
needed NPF) that differs across OpenTTD versions. Turning a screenshot into exact
(x, y, track piece, signal type, front tile) tuples that a script can stamp is
the open problem. We do not fake those coordinates. See the TODO(human) markers
in scenarios/openttdoom_gs/main.nut and STUCK.md.

## Tile footprint and timing, current estimate

These are planning estimates from the reference material, not measurements.

- Footprint. A single clocked NOR tile in the compact style is on the order of a
  handful of tiles, roughly a 4 by 4 to 8 by 8 patch once you include the input
  taps, the combo/exit signal evaluation, the output register and the local clock
  release. The place_and_route layer treats a cell as a w by h box (see
  PlacedCell in place_and_route/scenario.py), so the exact footprint becomes a
  constant once the geometry is solved. Until then place-and-route can reserve a
  generous box and we shrink it later.
- Latency. One clock edge per gate, by construction. gate_model.py asserts this:
  output at edge N is NOR of inputs as of edge N-1, and a two tile chain takes two
  edges.
- Absolute speed. Slow in normal OpenTTD. The zem.fi four bit adder, 17 gates,
  took "about two months of in game time for the carry information to propagate".
  That is fine for us. The brief plans a forked headless OpenTTD with a stripped
  tick loop and uncapped speed to make this usable, and that fork is explicitly
  out of scope for this run.

## Construction mechanism decision (the M2 choice)

The brief gives two ways to get this design onto the map:

(a) write the binary .sav savegame directly, which means implementing OpenTTD's
    chunked savegame format (the MAPT/MAPS map chunks, vehicle chunks, signal
    state, all version dependent and compressed), or

(b) drive construction with a GameScript (Squirrel) that builds the track,
    signals and trains when the scenario loads, using the documented GS API.

We choose (b), the GameScript, for M2 and for the whole pipeline. Rationale:

- The .sav format is binary, versioned, compressed (LZMA/zlib), and effectively
  undocumented outside the source. Every OpenTTD release can change chunk layout.
  Hand emitting it is high effort and extremely brittle, and a single wrong byte
  gives an unloadable or crashing save with no useful error.
- The GameScript API is documented, stable across the 14/15 API versions shipped
  with our binary (vendor/openttd has compat_14.nut, so the live API is 15), and
  has exactly the calls we need: GSRail.BuildRailTrack, GSRail.BuildSignal,
  GSMap.GetTileIndex, GSVehicle for the clock train, and so on.
- A GameScript is text we can diff, review and regenerate from place-and-route
  output. place_and_route/scenario.py already emits a flat Squirrel data table
  via to_nut(), so the GS just walks that table and stamps tiles. That keeps the
  emitter trivial and the geometry in data, not code.
- It fails loud. If a build call is rejected we get a GS error in the console and
  can inspect it, instead of a corrupt binary.

The one real catch, documented honestly: a GameScript runs as a "deity" with no
company by default, and building track requires a company context
(GSCompanyMode). So the GS has to either run in a game where a company exists and
borrow it, or the scenario has to provide one. This is a genuine open item, see
STUCK.md. It does not change the decision, the binary .sav path has strictly
worse versions of every one of these problems.

## Verification status, honest

- Verified here: scenarios/gate_model.py reproduces the NOR and NOT truth tables
  across clock cycles and shows the intended one edge latency. Run with
  `python -m pytest scenarios/test_gate_model.py -q`. This proves the INTENDED
  semantics are self consistent. It does NOT prove OpenTTD realises them.
- Not verified, and called out as TODO(human): the exact OpenTTD track and signal
  geometry of one NOR tile, the clock release timing, and that a GameScript can
  stamp it and make it compute when poked. We cannot run or test a GameScript in
  this environment, and the exact computing geometry is the open research problem.
  The GameScript skeleton in scenarios/openttdoom_gs/ marks every spot that needs
  real coordinates with TODO(human). STUCK.md lists the blockers with detail.

## Sources

- zem.fi, Logic Gates in OpenTTD, http://zem.fi/2005-10-21-ttd-logic
- openttdcoop wiki, Logic, https://wiki.openttdcoop.org/Logic
- openttdcoop wiki, Signals, https://wiki.openttdcoop.org/Signals
- openttdcoop blog, LED Counter and Logic Gates Part 1,
  https://blog.openttdcoop.org/2008/06/17/the-insane-led-counter-logic-gates-part-1/
- openttdcoop blog, Optimization of Logic, Logic Gates Part II,
  https://blog.openttdcoop.org/2009/01/18/optimization-of-logic-logic-gates-part-ii/
- OpenTTD manual, Signals, https://wiki.openttd.org/en/Manual/Signals
- OpenTTD junctionary, Advanced signalling examples,
  https://wiki.openttd.org/en/Community/Junctionary/Advanced%20signalling%20examples
- OpenTTD GameScript API, GSRail, https://docs.openttd.org/gs-api/classGSRail
- OpenTTD GameScript API, GSCompanyMode,
  https://docs.openttd.org/gs-api/classGSCompanyMode
- OpenTTD GameScript API, GSMap, https://docs.openttd.org/gs-api/classGSMap
