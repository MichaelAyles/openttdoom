#!/usr/bin/env bash
# build.sh: run the openttdoom toolchain end to end.
#
# Pipeline:
#   1. synth     emit gate-level netlists from the HDL (python synth/synth.py)
#   2. place+route + emit  lower the adder netlist to a placed OpenTTD scenario
#   3. install   copy the generated .nut into the GameScript so OpenTTD can load it
#   4. test      run the project's pytest suites
#
# Run scripts/setup.sh first so the binary and Python deps are in place.
#
# Usage: bash scripts/build.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

NETLIST="synth/out/adder4_nor.json"
SCENARIO="scenarios/adder4.scenario.json"
GS_DIR="scenarios/openttdoom_gs"
GS_NUT="${GS_DIR}/scenario_data.nut"

# --- 1. synthesise netlists ------------------------------------------------------
echo "[build] 1/4 synthesising netlists ..."
python synth/synth.py

# --- 2. place, route and emit the scenario ---------------------------------------
echo "[build] 2/4 place-and-route + emit scenario ..."
python -m place_and_route.emit "${NETLIST}" "${SCENARIO}"

# --- 3. install the GameScript data table ----------------------------------------
# emit writes the Squirrel data table next to the scenario JSON. The GameScript reads
# scenario_data.nut on load, so copy the freshly generated .nut into place.
echo "[build] 3/4 installing GameScript data ..."
mkdir -p "${GS_DIR}"
GENERATED_NUT="${SCENARIO%.json}.nut"
cp "${GENERATED_NUT}" "${GS_NUT}"

# --- 4. tests --------------------------------------------------------------------
echo "[build] 4/4 running test suites ..."
python -m pytest -q

# --- artifacts -------------------------------------------------------------------
echo ""
echo "[build] done. Artifacts:"
echo "  netlist:        ${NETLIST}"
echo "  scenario JSON:  ${SCENARIO}"
echo "  scenario .nut:  ${GENERATED_NUT}"
echo "  GameScript nut: ${GS_NUT}"
echo ""
echo "[build] load the scenario in OpenTTD via the openttdoom_gs GameScript,"
echo "[build] or run the headless smoke test with: bash scripts/run_headless.sh"
