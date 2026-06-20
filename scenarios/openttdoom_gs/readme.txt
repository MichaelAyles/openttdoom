openttdoom GameScript: install and run
======================================

This is the M2 construction mechanism: a GameScript (Squirrel) that, on load,
reads a baked scenario data table and stamps the openttdoom logic design onto the
OpenTTD map (NOR tiles, routed track, a clock train, input pads, output/pixel
signals).

Honest status. This is a skeleton. It registers, loads, reads the data table and
walks it with the real GS API, but the exact gate geometry is not solved, so it
does not yet build a computing gate. Every spot that needs real coordinates is
marked TODO(human) in main.nut. See ../GATE_DESIGN.md and the repo STUCK.md.
None of this has been run in game, there is no GS runtime in the build box.


Files
-----
  info.nut            GSInfo metadata, registers the script.
  main.nut            GSController, reads the table and stamps the design.
  scenario_data.nut   the baked design table (GetScenarioData()), example here,
                      normally overwritten by place_and_route/emit.py.
  readme.txt          this file.


Installing the GS
-----------------
A GameScript lives in OpenTTD's game/ directory, one folder per script.

1. Find your OpenTTD content dir. With the bundled binary in this repo it is the
   game/ folder next to openttd.exe:
     vendor/openttd/openttd-15.3-windows-win64/game/
   For a normal install it is your personal dir, e.g. on Windows
     Documents/OpenTTD/game/
   on Linux ~/.local/share/openttd/game/ or ~/.openttd/game/.

2. Copy this whole openttdoom_gs/ folder into that game/ directory, so you get
     game/openttdoom_gs/info.nut
     game/openttdoom_gs/main.nut
     game/openttdoom_gs/scenario_data.nut

3. Start OpenTTD. The script should appear as "openttdoom builder" in
   Settings -> Game Script. Select it. If it does not appear, see Troubleshooting.


Running it on a scenario
------------------------
The script builds on the map, which needs a company context (see the company
note below). The simplest reliable path while the skeleton matures:

1. Start a new game (or load a scenario) so a company exists. Found company 0 if
   the game did not create one (start a vehicle or place a depot once).

2. Open the console with the backtick/tilde key (`) or via the in-game menu.

3. Make sure the GameScript is selected (Settings -> Game Script), then start or
   restart it. Useful console commands:
     list_game_scripts        show available game scripts
     reload_game_script       reload and restart the selected GS (handy after edits)
     debug_level script=4     turn up GS logging so GSLog.Info lines show

4. Watch the console / AI-GS debug window. You should see the builder log the
   design name, cell/route counts, and one line per stamped piece, each followed
   by its TODO(human) reality (the geometry is placeholder).


Driving and inspecting (poking inputs, reading outputs)
-------------------------------------------------------
Once real gate geometry exists, you poke an input by injecting or removing a
train on an input pad's track, and you read an output by sampling its signal
state at the clock edge. Hooks for that:

  - The OpenTTD console `script` command (and the GS debug window) let you call
    into / inspect a running script and watch GSLog output.
  - For automated runs, drive headless:
      openttd.exe -D -g <yourscenario.scn>
    with the GS selected in the config, and read the console log.
  - The Python framebuffer viewer (golden/) reads pixel signal state out of the
    sim for clean frames; it samples the output/pixel tiles this GS wires up.

None of the poke/read loop is exercised yet, because the gate that turns a poked
input into a flipped output is the unsolved TODO(human) geometry.


The company-context caveat (important)
--------------------------------------
A GameScript runs as a "deity" with no company by default. Building track and
signals (GSRail.BuildRailTrack, GSRail.BuildSignal) requires a valid company,
entered via GSCompanyMode. So you must run the GS in a game where a company
exists, and the script borrows it (see PickCompany() / Build() in main.nut). If
no company exists, build calls are rejected and nothing stamps. This is an open
item, tracked in the repo STUCK.md.


Troubleshooting
---------------
  - Script not listed: check the folder is directly under game/ and contains
    info.nut with a RegisterGS(...) call. Re-scan via Settings -> Game Script ->
    refresh, or restart OpenTTD.
  - "Requires API version ...": this targets GS API "15" (OpenTTD 15.x). On an
    older OpenTTD, lower GetAPIVersion() in info.nut to a version that binary
    ships (its game/ dir lists compat_*.nut files), or update OpenTTD.
  - Nothing builds but the log runs: almost certainly the company-context caveat
    above, or the TODO(human) geometry simply not being implemented yet.
