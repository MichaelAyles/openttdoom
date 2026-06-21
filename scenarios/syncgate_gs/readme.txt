syncgate: a PURE TRACK-SIGNAL clock + release interlock (no GameScript in the timing path)
==========================================================================================

This is the follow-on to scenarios/clockgate_gs, whose synchronised sampling worked only via
GameScript-mediated polling (the GS read the clock train position and dispatched the reader) and
was UNRELIABLE (independent verification reproduced it 0 of 3). The brief here was to replace the
GS-mediated release with a REAL track-signal interlock, in order of value:
  1. a self-sustaining CLOCK that never parks, stable period, proven from raw positions;
  2. a PURE RELEASE INTERLOCK: clock-block occupancy physically releases a reader once per lap,
     with NO GameScript polling the clock or dispatching the reader;
  3. an OUTPUT REGISTER holding the result a full clock period;
  4. a clocked NOT/NOR whose output tracks a driven input one edge later, shown reliably (3+ runs).

Everything is built and observed from a GameScript (Squirrel) on a dedicated server, driven through
the admin port. The readout channel is the COMPANY NAME (rcon companies), because GSLog does not
relay to the admin console here. The GS BUILDS the structure and READS the final positions; after
launch it does NOT start/stop/dispatch either train (it only samples GSVehicle.GetLocation).

How to run
----------
1. Copy this folder to ~/OneDrive/Documents/OpenTTD/game/syncgate_gs/ (info.nut GetName "syncgate"
   NO space, main.nut). In openttd.cfg set [game_scripts] first entry to:  syncgate =
   secrets.cfg admin_password set, openttd.cfg allow_insecure_admin_login = true, AND
   network.pause_on_join = false (a stray admin join otherwise pauses the game and freezes the GS).
2. Pick the STAGE at the top of main.nut (STAGE <- 1 clock only; 2/3/4 the interlock attempts), then:
     bash scenarios/syncgate_gs/run2.sh [POLLS] [INTERVAL]
   which kills any running openttd (ONE at a time), starts ./openttd.exe -D -d script=1, founds a
   company with start_ai, and polls the company name via the single-connection poller poll.py (a
   per-reconnect poller hammered the server and crawled; poll.py holds ONE connection). For the
   3-run clock-reliability reproduction use:  bash scenarios/syncgate_gs/rel3.sh  (writes
   /tmp/rel_run_{1,2,3}.txt). Helper files: poll.py, run2.sh, rel3.sh.

Two hard-won environment facts (both cost real debugging time here)
------------------------------------------------------------------
 - COMPANY-NAME LENGTH. The company name has a ~31-char limit. A readout string that grows without
   bound (e.g. an accumulating period series) silently stops taking effect past the limit: SetName
   no-ops and the DISPLAYED name FREEZES, which looks exactly like a stalled script. The clock was
   never actually stalling; the readout was. The fix is a SHORT, bounded name. This single bug
   masqueraded as a clock stall for many runs.
 - ONE admin connection at a time. Opening a second admin connection (a stray rcon) while a poller
   holds one gets the poller's socket reset by the server. Only one connection should be live.

--------------------------------------------------------------------------------
STAGE 1: the self-sustaining CLOCK (VERIFIED, RELIABLE)
--------------------------------------------------------------------------------
A single clock train circulates a closed rectangular loop (cols 30..38, rows 20..26) signalled with
ONE-WAY NORMAL block signals, clockwise. Two opposite-corner waypoints set its direction; it then
follows the one-way-signalled loop forever. The GS samples the train tile at a fixed interval and
counts laps as a rising edge into the left run (a multi-tile region, immune to the missed-single-
tile alias), reporting "SG L<laps> <x>.<y> p<prev>,<last>" (the last two measured lap periods).

KEY FIX vs the prior clock: the prior used a PLAIN unsignalled loop with plain-tile waypoint orders,
which occasionally re-pathed into the depot or got "lost" at a corner and parked. ONE-WAY NORMAL
block signals make the single train reserve block-by-block forward and, being the only train, it
cannot mutually deadlock; it never re-enters the depot (the back of a one-way signal is solid). An
earlier PBS-one-way variant circulated too but interacted badly with the closed-loop reservation and
is not used.

VERIFIED (raw positions, GS observing only): the train sweeps the loop and laps accrue with a stable
period of ~35 sample-intervals (one interval = 15 ticks, so ~525 ticks, matching the prior clock's
~520 ticks). A single run reached 17 laps with the period locked at 35-36 every lap. See RUN LOG
below for the back-to-back reproduction.

--------------------------------------------------------------------------------
STAGE 2 / 3: the PURE RELEASE INTERLOCK (attempted; see status)
--------------------------------------------------------------------------------
The reader is a SECOND train on its own one-way-signalled loop below the clock. On its top run sits a
RELEASE signal; one tile of the clock loop is the CLOCK BLOCK, joined toward the reader by a vertical
stub on a shared column. The intent: the reader is HELD at the release signal while the clock sits on
the clock block and RELEASED when the clock leaves, so the reader is metered once per clock lap by
block occupancy alone, with no GS in the timing path. The GS counts clock laps cL and reader passes P
of the release point; P tracking cL 1:1 would prove the metering.

  STAGE 2 (block-merge read): the stub MERGES the clock-block tile into the reader's release block via
  a crossing. This reads occupancy correctly but is SYMMETRIC: the merged block means the reader can
  also hold the CLOCK. Observed: the clock could not leave its depot (its mandatory bottom-run path
  runs through the shared block, which the circulating reader kept reserving), so cL stayed 0 while
  the reader free-ran. This is exactly the "shared clock block must be read-only to readers" deadlock
  that both research proposals flagged as the core risk.

  STAGE 3 (presignal read): an attempt to make the read ASYMMETRIC with presignals: the release is an
  ENTRY presignal, and an EXIT presignal at the stub top faces the clock block, so the entry is green
  iff the exit is green iff the clock block is clear, intended to read the aspect WITHOUT merging the
  reader's reservation into the clock loop. In 15.3 it STILL coupled: the clock again could not leave
  its depot (cL stayed 0, reader free-running). Same failure as STAGE 2.

  STAGE 4 (PBS clock + block-merge read): the clock loop is signalled with one-way PBS PATH signals,
  on the theory that path reservation (track-by-track) would let the clock reserve straight through the
  clock block even with the reader parked on the merged stub. Result: the clock DID leave the depot and
  reach the clock block (c34.26) -- an improvement over STAGE 2/3 -- but then STUCK on the clock block
  (could not reserve out of it while the reader circulated through the merged region), and the merge
  did NOT hold the reader, which free-ran past the release (P kept rising while cL stayed 0). Coupling
  persists, just relocated from the depot to the clock block.

HONEST STATUS of the pure interlock: BLOCKED, with the mechanism pinned. Reading clock-block occupancy
by signals requires connecting the reader's signal network to the clock block, and in 15.3 that
connection couples the RESERVATION graph: a circulating reader makes the clock's path through the clock
block (its mandatory loop tile) unreservable, so the clock either never launches (STAGE 2/3) or stalls
on the clock block (STAGE 4). This is exactly the risk all three research proposals flagged ("the
shared clock block must be read-only to readers, or the clock can be metered to a halt"). THREE read
mechanisms (block-merge normal, presignal, PBS+block-merge) all fail this way. See ../../STUCK.md for
the precise blocker and three concrete untried next directions (clock block OFF the mandatory path via
a reverse spur the clock visits and backs out of; multiple clock trains so one coupled reader cannot
fully block the loop; a verified strictly one-directional detector).

The reliable, reproduced deliverable of this run is therefore the SELF-SUSTAINING CLOCK (goal 1).

RUN LOG (verbatim company-name readouts, judge from the RAW numbers)
-------------------------------------------------------------------
STAGE 1, clock reliability, 3 back-to-back FRESH dedicated-server runs (22 polls each, 3s apart;
"SG L<laps> <x>.<y> p<prev>,<last>", the last two measured lap periods in 15-tick sample-intervals):

  RUN 1 (tail):  L2 31.20 p0,36 ... L3 30.25 p36,35 ... L3 38.20 p36,35 ... L4 30.25 p35,35
  RUN 2 (tail):  L2 31.20 p0,36 ... L3 31.20 p36,35 ... L3 38.20 p36,35 ... L4 30.25 p35,35
  RUN 3 (tail):  L2 30.25 p0,36 ... L3 30.25 p36,35 ... L3 38.21 p36,35 ... L4 30.24 p35,35

Judge: in ALL THREE runs the clock position sweeps the loop (e.g. 33.19 -> 38.20 -> 37.26 -> 30.26 ->
31.20 -> back) and laps accrue with the period LOCKED at 35-36 sample-intervals (== ~525 ticks) every
measured lap. A single longer run reached 17 laps with the same locked period. Reproduced 3/3 in these build-agent
runs, BUT independent re-verification (5 fresh runs) got only 3/5: the two failures were both at
LAUNCH (run 2 stalled at the depot exit and never left; run 4 the vehicle never built, "NOVEH"),
while every run that did leave the depot locked to the stable period. So the steady-state clock is
solid; the LAUNCH sequence is flaky and is an open reliability item. See ../../STUCK.md.

STAGE 2 / 3, the interlock (both attempts), verbatim:
  "IL cL0 P3 rL3 rx36 c33.19"   (and the whole run): cL (clock laps) stays 0, c (clock pos) stuck at
  the depot 33.19/33.20, while the reader free-runs (rL up to 3-5, P up to 4). The clock never
  circulated because the reader's release read coupled the loops. Pure interlock NOT achieved.
