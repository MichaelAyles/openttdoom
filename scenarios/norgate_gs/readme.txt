norgate_gs: a VERIFIED computing gate in OpenTTD 15.3
=====================================================

This is the first piece of real, in-game logic for openttdoom. It builds a single
gate out of OpenTTD track and a block signal, then PROVES it computes by poking the
input(s) and watching the output flip. Everything is built and observed from a
GameScript (Squirrel), driven headlessly via the admin port.

Two GameScripts, both verified in game (not modelled, actually run):

  main_not_poke.nut   A NOT (one-input NOR). The SAME physical gate is poked twice:
                      input absent -> output 1, input present -> output 0.
                      Verified result (verbatim GSLog):
                        A=0 -> NOT=1   (reader reached east depot)
                        A=1 -> NOT=0   (reader held at the signal)
                        RESULT: PASS - the SAME gate flipped when poked.

  main_nor2.nut       A TWO-input NOR (the universal gate). All four input
                      combinations swept on one structure. Verified result:
                        NOR(0,0)=1  NOR(0,1)=0  NOR(1,0)=0  NOR(1,1)=0
                        RESULT: PASS - all four rows match NOR(a,b).

main.nut is a copy of main_nor2.nut (the headline NOR result).

How the gate works
------------------
A net's bit is a train present (1) or absent (0) on a piece of track. A block
signal is GREEN iff the block ahead is empty, RED iff a train is in it. So a reader
train placed before the signal passes it iff the protected block (the INPUT block)
is empty, i.e. iff every input train is absent. That is NOR. The output is read by
observing WHERE the reader ends up (GSVehicle.GetLocation): past the signal (the
east depot) means 1, held at the signal means 0. The GS API exposes no signal
aspect read and GSTile cannot see a vehicle, so routing-the-reader-and-reading-its
position is the observability trick that makes this work.

Exact geometry (read back from the proven save, lane row Y=42, x east):
    [west depot @39] === [reader SIG @46] in-taps @47,@48 [term SIG @50] [east depot @52]
  - reader signal and terminating signal are normal block signals.
  - CRITICAL: GSRail.BuildSignal(tile, front) permits travel FROM front INTO tile.
    For an eastbound reader the reader signal needs front = SIGX-1 (the tile WEST
    of it). front = SIGX+1 builds a westbound-permissive signal that blocks the
    reader unconditionally (looks like a dead gate). This is the opposite of the
    naive guess and was the key fact.
  - The terminating signal closes the input block so it is a through block. A normal
    signal in front of a dead-end block (e.g. straight into a depot) stays red even
    when empty, which also looks like a dead gate.
  - The build area is demolished and LevelTiles'd first; rail will not build on the
    lakes a random map drops onto fixed coordinates.

How to run it (headless, on the bundled binary)
-----------------------------------------------
1. Copy this folder to the OpenTTD game dir:
     ~/OneDrive/Documents/OpenTTD/game/norgate_gs/
   (or use the existing game/norprobe/ which is where it was developed).
2. Select it as the game script in openttd.cfg [game_scripts], and set:
     [pf] is fine at defaults; the gate uses only normal block signals.
   The dev runs used: terrain flat, no water borders, no rivers, no towns/industry,
   a large max_loan, admin_password set and allow_insecure_admin_login=true.
3. Start a dedicated server from the binary dir:
     ./openttd.exe -D -d script=4
4. Found a company for the deity GS to build as, and watch it compute:
     python tools/ottd_admin.py rcon "start_ai"
     python tools/ottd_admin.py watch 160
   The NOR sweep takes a couple of minutes of in-game time (four reader runs).

Proven saves: norgate_proven.sav (NOT), norgate2_proven.sav (NOR), in the OpenTTD
save dir.

Honest scope
------------
Verified here: a single combinational NOT and a single combinational 2-input NOR
compute correctly in OpenTTD 15.3, built and observed entirely from a GameScript.
NOT verified here: the clock train (this gate is run on demand, not clock-sampled),
chaining one gate's output into the next gate's input, the one-edge register
latency, and the framebuffer readout. Those now have a concrete, working foundation.
See ../GATE_DESIGN.md (the "SOLVED AND VERIFIED" section) and ../../STUCK.md.
