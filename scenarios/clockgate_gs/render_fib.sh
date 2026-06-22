#!/usr/bin/env bash
# Capture a REAL screenshot of the live fibgate map (the clock loop + the 4-lane NOR gate
# bank that produces the Fibonacci readout). Runs the GS headless, polls the company name
# until the gate bank is built and computing (an "e<k> ..." per-edge readout appears), then
# RCON-saves the live map, kills the server, loads the save in a GUI run and screenshots it.
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
PERSONAL="$HOME/OneDrive/Documents/OpenTTD"
SAVE="fibgate_live"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

taskkill //F //IM openttd.exe >/dev/null 2>&1; sleep 2
( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
for i in $(seq 1 25); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then break; fi; done
$ADMIN rcon "start_ai" >/dev/null 2>&1

# poll until the gate bank is built AND computing: wait for an "e<k>" per-edge readout
saved=""
for i in $(seq 1 200); do
  nm="$(cname)"
  echo "  [i$i] $nm"
  case "$nm" in
    "e2 "*|"e3 "*|"e4 "*|"F "[0-9]*)
      # bank is built and several edges computed; save the live map now
      $ADMIN rcon "save $SAVE" >/dev/null 2>&1
      saved="yes"; echo "  RCON-saved live map as $SAVE at readout: $nm"; break;;
    "CKFAIL"*) echo "  CKFAIL (clock did not launch); retry render"; break;;
  esac
  sleep 3
done
sleep 2
taskkill //F //IM openttd.exe >/dev/null 2>&1; sleep 2

if [ -z "$saved" ]; then echo "RENDER FAILED (no live save; clock likely CKFAILed)"; exit 1; fi
if [ ! -f "$PERSONAL/save/$SAVE.sav" ]; then echo "RENDER FAILED (save file missing)"; exit 1; fi

# GUI run: screenshot the loaded live map (minimap + a normal viewport screenshot)
cat > "$BIN/scripts/game_start.scr" <<EOF
screenshot minimap fibgate_live_mini
screenshot normal fibgate_live_view
EOF
rm -f "$PERSONAL/screenshot/fibgate_live_mini.png" "$PERSONAL/screenshot/fibgate_live_view.png"
( cd "$BIN" && ./openttd.exe -g "$PERSONAL/save/$SAVE.sav" -snull -mnull >/dev/null 2>&1 & )
sleep 16
taskkill //F //IM openttd.exe >/dev/null 2>&1; sleep 2
ls -la "$PERSONAL/screenshot/fibgate_live_"*.png 2>/dev/null
echo "RENDER DONE"
