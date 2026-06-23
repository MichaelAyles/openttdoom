#!/usr/bin/env bash
# ADVERSARIAL fresh-run verifier for the self-feeding toggle. Owned by the verifier.
# For each run: kill openttd, relaunch dedicated, start_ai Idle, poll the company name,
# print EVERY distinct readout (per-edge e<k> Q<q> x<rawx> N<next> n<count> and final TG).
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
RUNS="${1:-5}"

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
  final=""
  last=""
  for i in $(seq 1 200); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then echo "  [r$run i$i] $nm"; last="$nm"; fi
    if echo "$nm" | grep -qE "^TG [01e]{6}"; then final="$(echo "$nm" | grep -oE 'TG [01e]{6}')"; break; fi
    if echo "$nm" | grep -qiE "CKFAIL|TG ERR|REENTRY"; then final="$(echo "$nm")"; break; fi
    sleep 2
  done
  if [ -z "$final" ]; then final="TIMEOUT(last=$last)"; fi
  echo "########## RUN $run RESULT: $final ##########"
done
echo "ALL RUNS DONE $(date +%H:%M:%S)"
