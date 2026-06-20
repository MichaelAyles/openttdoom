#!/usr/bin/env bash
# run_headless.sh: run the verified headless OpenTTD smoke test.
#
# This drives the prebuilt binary with the null video, sound and music drivers and
# a fixed tick budget, then exits. It proves the binary launches, loads OpenGFX,
# spins the tick loop and shuts down cleanly with no GUI and no input.
#
# Usage:
#   bash scripts/run_headless.sh [TICKS]
# TICKS defaults to 20000. Example: bash scripts/run_headless.sh 60000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

TICKS="${1:-20000}"
OPENTTD="vendor/openttd/openttd-15.3-windows-win64/openttd.exe"

if [ ! -f "${OPENTTD}" ]; then
  echo "[run_headless] binary not found at ${OPENTTD}"
  echo "[run_headless] run scripts/setup.sh first."
  exit 1
fi

echo "[run_headless] running ${TICKS} ticks with null drivers ..."
# -x         exit right after the run completes
# -vnull     null video driver, runs for ticks=N then stops
# -snull     null sound driver
# -mnull     null music driver
time "${OPENTTD}" -x "-vnull:ticks=${TICKS}" -snull -mnull
echo "[run_headless] exit code: $?  (0 == success)"

# GUI-subsystem caveat:
# The Windows release binary is linked as a GUI subsystem app, so its stdout is not
# piped back to this shell. You will not see OpenTTD log lines here. That is expected
# and does not mean it failed silently. Success is shown two ways:
#   1. the exit code is 0, and
#   2. the wall-clock time scales with the tick count, at roughly 6000 ticks/sec on
#      this machine (so the default 20000 ticks takes about 3 seconds). If the time
#      tracks the tick budget you gave it, the tick loop really ran.
