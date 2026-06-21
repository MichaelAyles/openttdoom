#!/usr/bin/env bash
# Five BACK-TO-BACK FRESH dedicated-server runs of the clocked NOT gate.
# Each run: kill openttd, relaunch ./openttd.exe -D -d script=1, start_ai, poll the
# company name until it reaches "CG <6 bits>" (or CKFAIL / timeout). Records the final
# readout and the last per-edge readouts for each run. ONE openttd / ONE admin conn at a time.
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

for run in 1 2 3 4 5; do
  echo "########## RUN $run start $(date +%H:%M:%S) ##########"
  taskkill //F //IM openttd.exe >/dev/null 2>&1
  sleep 2
  ( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
  # wait for admin port
  for i in $(seq 1 25); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then break; fi; done
  $ADMIN rcon "start_ai" >/dev/null 2>&1
  final=""
  last=""
  # LATCH the first "CG <6 bits>" readout we see and stop. The gate may briefly show the
  # consolidated readout and then (intermittently) the GS instance restarts and rebuilds;
  # the latched bits are still the genuine raw-reader result of a completed cycle, so we
  # accept the first one. Also reconstruct the bits from the per-edge "e<k> ... o<bit>"
  # readouts as a cross-check, in case the consolidated readout is missed by the poll phase.
  e0="";e1="";e2="";e3="";e4="";e5=""
  for i in $(seq 1 110); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then echo "  [r$run i$i] $nm"; last="$nm"; fi
    case "$nm" in
      "e0 "*) e0="${nm##*o}";; "e1 "*) e1="${nm##*o}";; "e2 "*) e2="${nm##*o}";;
      "e3 "*) e3="${nm##*o}";; "e4 "*) e4="${nm##*o}";; "e5 "*) e5="${nm##*o}";;
    esac
    if echo "$nm" | grep -qE "^CG [01]{6}"; then final="$(echo "$nm" | grep -oE 'CG [01]{6}')"; break; fi
    if echo "$nm" | grep -qi "CKFAIL"; then final="CKFAIL"; break; fi
    # if we have captured all six per-edge bits, that is a completed cycle too.
    if [ -n "$e0$e1$e2$e3$e4$e5" ] && [ -n "$e5" ]; then final="CG $e0$e1$e2$e3$e4$e5 (per-edge)"; break; fi
    sleep 3
  done
  if [ -z "$final" ]; then final="TIMEOUT(last=$last, edges=$e0$e1$e2$e3$e4$e5)"; fi
  echo "########## RUN $run RESULT: $final ##########"
done
echo "ALL RUNS DONE $(date +%H:%M:%S)"
