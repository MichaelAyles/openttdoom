#!/usr/bin/env bash
# N BACK-TO-BACK FRESH dedicated-server runs of the SELF-FEEDING FIBONACCI.
# Each run: sync the GS into the game dir, kill openttd, relaunch ./openttd.exe -D -d script=1,
# start_ai Idle, poll the company name until "FF <terms>" (or CKFAIL / FF ERR / timeout). Prints
# every distinct company-name readout (the per-edge "e<k> a<av> b<bv> s<sum> n<count>" lines and
# the final "FF 1 1 2 3 ..."). ONE openttd / ONE admin connection at a time.
#
# Expected (full): FF 1 1 2 3 5 8 13  (a=0,b=1; next = a+b via the NOR full adder, shifted back).
# Judge from the RAW per-edge reads: each output term is next read off the gates, every sum bit a
# raw block-signal NOR pass/hold. Reliability compounds, so an honest partial (e.g. FF 1 1 2) with
# the mechanism pinned is the expected real result.
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
SRC="$ROOT/scenarios/selffib_gs"
DST="$HOME/OneDrive/Documents/OpenTTD/game/selffib_gs"
ADMIN="python $ROOT/tools/ottd_admin.py"
RUNS="${1:-4}"
POLLS="${2:-220}"

mkdir -p "$DST"
cp "$SRC/main.nut" "$DST/main.nut"
cp "$SRC/info.nut" "$DST/info.nut"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

for run in $(seq 1 "$RUNS"); do
  echo "########## RUN $run start $(date +%H:%M:%S) ##########"
  taskkill //F //IM openttd.exe >/dev/null 2>&1
  sleep 2
  ( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
  up=0
  for i in $(seq 1 30); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then up=1; break; fi; done
  if [ "$up" != 1 ]; then echo "  [r$run] SERVER NEVER CAME UP"; continue; fi
  $ADMIN rcon "start_ai Idle" >/dev/null 2>&1
  final=""; last=""; t0=$(date +%s)
  for i in $(seq 1 "$POLLS"); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then echo "  [r$run +$(($(date +%s)-t0))s] $nm"; last="$nm"; fi
    if echo "$nm" | grep -qE "^FF [0-9e]"; then final="$nm"; break; fi
    if echo "$nm" | grep -qiE "CKFAIL|FF ERR|FF REENTRY"; then final="$nm"; break; fi
    sleep 3
  done
  if [ -z "$final" ]; then final="TIMEOUT(last=$last)"; fi
  echo "########## RUN $run RESULT: $final (+$(($(date +%s)-t0))s) ##########"
done
echo "ALL RUNS DONE $(date +%H:%M:%S)"
