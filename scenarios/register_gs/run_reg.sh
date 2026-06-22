#!/usr/bin/env bash
# N BACK-TO-BACK FRESH dedicated-server runs of the clocked 1-bit register.
# Each run: kill openttd, relaunch ./openttd.exe -D -d script=1, start_ai, poll the
# company name until it reaches "RG <5 bits>" (or CKFAIL / timeout). Prints each new
# company-name readout (the per-edge "e<k> x<rawx> q<bit> ..." lines and the final
# "RG 11100"). ONE openttd / ONE admin connection at a time.
#
# Expected: RG 11100  (edge schedule W1,-,-,W0,-, Q = 1,1,1,0,0).
# Judge from the RAW per-edge x: q=1 iff reader held at/before RSIGX (x <= 46),
# q=0 iff reader passed (x > 46).
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
  for i in $(seq 1 130); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then echo "  [r$run i$i] $nm"; last="$nm"; fi
    if echo "$nm" | grep -qE "^RG [01]{5}"; then final="$(echo "$nm" | grep -oE 'RG [01]{5}')"; break; fi
    if echo "$nm" | grep -qi "CKFAIL"; then final="CKFAIL"; break; fi
    sleep 3
  done
  if [ -z "$final" ]; then final="TIMEOUT(last=$last)"; fi
  echo "########## RUN $run RESULT: $final ##########"
done
echo "ALL RUNS DONE $(date +%H:%M:%S)"
