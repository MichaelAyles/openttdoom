#!/usr/bin/env bash
# ADVERSARIAL fresh-run verifier for the self-feeding Fibonacci. For each run: kill openttd,
# relaunch dedicated, start_ai Idle, poll the company name, print EVERY distinct readout (the
# per-edge "e<k> a<av> b<bv> s<sum> n<count>" lines and the final "FF 1 1 2 3"). Judges from the
# RAW per-edge reads. ONE openttd / ONE admin connection at a time. Does NOT re-sync the game dir
# (verifies whatever is installed), so an independent verifier sees exactly what was deployed.
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
RUNS="${1:-5}"
POLLS="${2:-300}"

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
