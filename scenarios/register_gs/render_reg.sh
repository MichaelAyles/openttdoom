#!/usr/bin/env bash
# Capture a REAL screenshot of the live register map (the clock loop + the register lane
# with the HOLD train parked = the stored bit). Runs the register GS headless, polls the
# company name until the register is built and HOLDING (an "e1"/"e2" per-edge readout, where
# the bit has been held across a clock edge), then RCON-saves the live map, kills the
# server, loads the save in a GUI run and screenshots it (minimap + a normal viewport).
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
PERSONAL="$HOME/OneDrive/Documents/OpenTTD"
SAVE="register_live"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

taskkill //F //IM openttd.exe >/dev/null 2>&1; sleep 2
( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
for i in $(seq 1 25); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then break; fi; done
$ADMIN rcon "start_ai Idle" >/dev/null 2>&1

# poll until the register is built AND holding: wait for an "e1"/"e2" per-edge readout
# (the bit has been written and held across at least one clock edge).
saved=""
for i in $(seq 1 200); do
  nm="$(cname)"
  echo "  [i$i] $nm"
  case "$nm" in
    "e1 "*|"e2 "*)
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

# GUI run: scroll the viewport onto the register structures, then screenshot. The register
# lane is around (x=46, y=40) with the HOLD tile at (47,40); the clock loop is at x=30..37,
# y=20..25. Centre on the lane (the HOLD train + reader signal) for a close view, and on a
# midpoint for a wider view that catches both the clock loop and the lane.
cat > "$BIN/scripts/game_start.scr" <<EOF
zoomto 1
scrollto instant 47 40
screenshot normal register_live_lane
scrollto instant 38 32
screenshot normal register_live_both
screenshot minimap register_live_mini
EOF
rm -f "$PERSONAL/screenshot/register_live_lane.png" "$PERSONAL/screenshot/register_live_both.png" "$PERSONAL/screenshot/register_live_mini.png"
( cd "$BIN" && ./openttd.exe -g "$PERSONAL/save/$SAVE.sav" -snull -mnull >/dev/null 2>&1 & )
sleep 20
taskkill //F //IM openttd.exe >/dev/null 2>&1; sleep 2
ls -la "$PERSONAL/screenshot/register_live_"*.png 2>/dev/null
echo "RENDER DONE"
