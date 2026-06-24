#!/usr/bin/env bash
# LAUNCH-ONLY diagnostic: run N fresh dedicated servers and, for each, record the company-name
# progression ONLY up to the clock-launch verdict (clkOK or CKFAIL). Kills the server as soon as
# the verdict is in, so each iteration is short. Records, per run: the verdict, the LAST name seen
# before the verdict (so a stall is attributed to a phase), and the iteration count.
# This isolates the clock-LAUNCH yield from the rest of the machine.
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
BIN="$ROOT/vendor/openttd/openttd-15.3-windows-win64"
ADMIN="python $ROOT/tools/ottd_admin.py"
RUNS="${1:-10}"

cname() { $ADMIN rcon "companies" 2>/dev/null | grep -i "Company Name" | head -1 | sed -n "s/.*Company Name: '\([^']*\)'.*/\1/p"; }

ok=0; fail=0; other=0
for run in $(seq 1 "$RUNS"); do
  taskkill //F //IM openttd.exe >/dev/null 2>&1
  sleep 2
  ( cd "$BIN" && ./openttd.exe -D -d script=1 >/dev/null 2>&1 & )
  up=0
  for i in $(seq 1 30); do sleep 1; if $ADMIN rcon "echo up" 2>/dev/null | grep -qi up; then up=1; break; fi; done
  if [ "$up" != 1 ]; then echo "RUN $run: SERVER-NEVER-UP"; other=$((other+1)); continue; fi
  $ADMIN rcon "start_ai Idle" >/dev/null 2>&1
  verdict=""; last=""
  # window must comfortably exceed the GS internal launch budget (egress + a full lap) so a
  # slow-but-good launch is never misread as a stall: ~150 * 1.2s ~= 3 min.
  for i in $(seq 1 150); do
    nm="$(cname)"
    if [ -n "$nm" ] && [ "$nm" != "$last" ]; then last="$nm"; fi
    # verdict: clkOK (any TG that is past clk.. and not CKFAIL) or CKFAIL.
    if echo "$nm" | grep -qi "CKFAIL"; then verdict="CKFAIL"; break; fi
    if echo "$nm" | grep -qiE "clkOK|^e[0-9]|^TG [01e]{6}"; then verdict="clkOK"; break; fi
    if echo "$nm" | grep -qiE "TG ERR|REENTRY"; then verdict="$nm"; break; fi
    sleep 1
  done
  [ -z "$verdict" ] && verdict="TIMEOUT(last=$last)"
  case "$verdict" in
    clkOK)  ok=$((ok+1));   echo "RUN $run: clkOK    (last=$last)";;
    CKFAIL) fail=$((fail+1)); echo "RUN $run: CKFAIL  (last=$last)";;
    *)      other=$((other+1)); echo "RUN $run: $verdict";;
  esac
done
taskkill //F //IM openttd.exe >/dev/null 2>&1
echo "===== LAUNCH YIELD: $ok/$RUNS clkOK, $fail CKFAIL, $other other ====="
