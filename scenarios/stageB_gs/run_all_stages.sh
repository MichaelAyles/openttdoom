#!/usr/bin/env bash
# Run the three FIXED-NETWORK stages back to back, N fresh dedicated-server runs each, reading
# every per-combo readout from the company name. These prove the norchain fixed signal-free
# coupling composes past two gates into a working half-adder, with NO per-gate train re-parked
# between reads (the fix for the selffib reused-lane collapse, STUCK.md #9).
#
#   STAGE A  stageA       3-gate chain   g2 = NOT(NOR(NOR(a,b),a))   expect 1,0,1,1
#   STAGE B  stageB       6-gate XOR     sum = a XOR b               expect 0,1,1,0
#   carry    stageBcarry  3-gate AND     carry = a AND b             expect 0,0,0,1
#
# ONE openttd / ONE admin connection at a time (the runner enforces this). Judge from RAW x.
set -u
ROOT="C:/Users/mikea/OneDrive/Desktop/Projects/openTTDOOM"
RUNS="${1:-4}"
PY="python $ROOT/tools/run_fixed.py"

echo "===== STAGE A (3-gate chain, expect STGA s42 -> 1,0,1,1) ====="
$PY --gsname stageA      --gsdir stageA_gs      --prefix "STGA s" --minfields 6 --timeout 300 --runs "$RUNS"
echo "===== STAGE B (6-gate XOR sum, expect STGB s49 -> 0,1,1,0) ====="
$PY --gsname stageB      --gsdir stageB_gs      --prefix "STGB s" --minfields 6 --timeout 420 --runs "$RUNS"
echo "===== carry (3-gate AND, expect STBC s38 -> 0,0,0,1) ====="
$PY --gsname stageBcarry --gsdir stageBcarry_gs --prefix "STBC s" --minfields 6 --timeout 300 --runs "$RUNS"
echo "ALL STAGES DONE"
