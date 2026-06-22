#!/usr/bin/env bash
# Fresh dedicated-server passes of the clock-stepped Fibonacci gate bank.
# Each run: kill openttd, relaunch ./openttd.exe -D -d script=1, start_ai, poll the company
# name until it reaches "F <values>" (final), CKFAIL, or timeout. Latches the first final
# readout and also reconstructs from the per-edge "e<k> v<val> ..." readouts as a cross-check.
# ONE openttd / ONE admin conn at a time. Pass the run count as $1 (default 3).
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
RUNS="${1:-3}"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

for run in $(seq 1 "$RUNS"); do
  echo "########## RUN $run start $(date +%H:%M:%S) ##########"
  taskkill //F //IM openttd.exe >/dev/null 2>&1
  sleep 2
  ( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
  for i in $(seq 1 25); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then break; fi; done
  $ADMIN rcon "start_ai" >/dev/null 2>&1
  final=""
  last=""
  # capture per-edge values e0..e6 as a cross-check
  declare -A ev
  for k in 0 1 2 3 4 5 6; do ev[$k]=""; done
  for i in $(seq 1 380); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then echo "  [r$run i$i] $nm"; last="$nm"; fi
    # per-edge: "e<k> v<val> b<bits> p<wait>"
    case "$nm" in
      "e0 v"*) ev[0]="$(echo "$nm" | sed -n 's/^e0 v\([0-9]*\).*/\1/p')";;
      "e1 v"*) ev[1]="$(echo "$nm" | sed -n 's/^e1 v\([0-9]*\).*/\1/p')";;
      "e2 v"*) ev[2]="$(echo "$nm" | sed -n 's/^e2 v\([0-9]*\).*/\1/p')";;
      "e3 v"*) ev[3]="$(echo "$nm" | sed -n 's/^e3 v\([0-9]*\).*/\1/p')";;
      "e4 v"*) ev[4]="$(echo "$nm" | sed -n 's/^e4 v\([0-9]*\).*/\1/p')";;
      "e5 v"*) ev[5]="$(echo "$nm" | sed -n 's/^e5 v\([0-9]*\).*/\1/p')";;
      "e6 v"*) ev[6]="$(echo "$nm" | sed -n 's/^e6 v\([0-9]*\).*/\1/p')";;
    esac
    # final consolidated readout "F <vals>" (vals contain digits and spaces)
    if echo "$nm" | grep -qE "^F [0-9]"; then final="$nm"; break; fi
    if echo "$nm" | grep -qi "CKFAIL"; then final="CKFAIL"; break; fi
    # all 7 per-edge values captured == a completed cycle too
    if [ -n "${ev[0]}" ] && [ -n "${ev[6]}" ]; then
      final="F ${ev[0]} ${ev[1]} ${ev[2]} ${ev[3]} ${ev[4]} ${ev[5]} ${ev[6]} (per-edge)"; break;
    fi
    sleep 2
  done
  if [ -z "$final" ]; then final="TIMEOUT(last=$last; edges=${ev[0]},${ev[1]},${ev[2]},${ev[3]},${ev[4]},${ev[5]},${ev[6]})"; fi
  echo "########## RUN $run RESULT: $final ##########"
done
echo "ALL RUNS DONE $(date +%H:%M:%S)"
taskkill //F //IM openttd.exe >/dev/null 2>&1
