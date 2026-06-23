#!/usr/bin/env bash
# N BACK-TO-BACK FRESH dedicated-server runs of the SELF-FEEDING 1-bit toggle.
# Each run: kill openttd, relaunch ./openttd.exe -D -d script=1, start_ai, poll the company
# name until it reaches "TG <6 bits>" (or CKFAIL / timeout). Prints each new company-name
# readout (the per-edge "e<k> Q<q> rx<regx> nx<notx> N<next>" lines and the final "TG 010101").
# ONE openttd / ONE admin connection at a time.
#
# Expected: TG 010101  (Q initialised to 0; next = NOT(held Q) from the physical NOT gate).
# Judge from the RAW per-edge register x (rx): q=1 iff held at/before RSIGX (rx <= 46),
# q=0 iff passed (rx > 46); and the next value nx is the NOT lane's raw reader x (>46 => 1).
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
RUNS="${1:-4}"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

for run in $(seq 1 "$RUNS"); do
  echo "########## RUN $run start $(date +%H:%M:%S) ##########"
  taskkill //F //IM openttd.exe >/dev/null 2>&1
  sleep 2
  ( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
  for i in $(seq 1 25); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then break; fi; done
  # start the IDLE AI specifically: a bare "start_ai" picks a RANDOM installed AI, and if it
  # picks "LoopBench" that AI floods the company with its own trains (which GSVehicleList then
  # counts, tripping the jam guard). Idle does nothing, so only the GS builds. (Same choice as
  # register_gs/render_reg.sh.)
  $ADMIN rcon "start_ai Idle" >/dev/null 2>&1
  final=""
  last=""
  for i in $(seq 1 160); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then echo "  [r$run i$i] $nm"; last="$nm"; fi
    if echo "$nm" | grep -qE "^TG [01e]{6}"; then final="$(echo "$nm" | grep -oE 'TG [01e]{6}')"; break; fi
    if echo "$nm" | grep -qi "CKFAIL"; then final="CKFAIL"; break; fi
    sleep 3
  done
  if [ -z "$final" ]; then final="TIMEOUT(last=$last)"; fi
  echo "########## RUN $run RESULT: $final ##########"
done
echo "ALL RUNS DONE $(date +%H:%M:%S)"
