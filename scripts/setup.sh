#!/usr/bin/env bash
# setup.sh: reproduce the openttdoom build environment.
#
# Target: Git-Bash / MINGW on Windows (the environment this repo was built in).
# This mirrors exactly what was done here. It pulls the prebuilt OpenTTD binary
# and OpenGFX, then installs the Python toolchain. yosys and verilator are
# OPTIONAL and were NOT installed in this environment, see the note at the bottom.
#
# Idempotent where reasonable: downloads and unzips are skipped if the target
# already exists. Re-running is safe.

set -euo pipefail

# Resolve repo root from this script's location so it runs from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

VENDOR="vendor/openttd"
OPENTTD_DIR="${VENDOR}/openttd-15.3-windows-win64"
OPENTTD_ZIP="${VENDOR}/openttd.zip"
OPENTTD_URL="https://cdn.openttd.org/openttd-releases/15.3/openttd-15.3-windows-win64.zip"

OPENGFX_ZIP="${VENDOR}/opengfx-8.0-all.zip"
OPENGFX_URL="https://cdn.openttd.org/opengfx-releases/8.0/opengfx-8.0-all.zip"
BASESET="${OPENTTD_DIR}/baseset"
OPENGFX_TAR="${BASESET}/opengfx-8.0.tar"

mkdir -p "${VENDOR}"

# --- OpenTTD 15.3 prebuilt win64 binary ------------------------------------------
# We use the prebuilt binary because this environment has no C++ compiler. See the
# "build from source" note at the bottom for the CMake alternative a human can use.
if [ -d "${OPENTTD_DIR}" ] && [ -f "${OPENTTD_DIR}/openttd.exe" ]; then
  echo "[setup] OpenTTD already present at ${OPENTTD_DIR}, skipping download."
else
  if [ ! -f "${OPENTTD_ZIP}" ]; then
    echo "[setup] downloading OpenTTD 15.3 win64 ..."
    curl -fL "${OPENTTD_URL}" -o "${OPENTTD_ZIP}"
  fi
  echo "[setup] unzipping OpenTTD ..."
  unzip -q -o "${OPENTTD_ZIP}" -d "${VENDOR}"
fi

# --- OpenGFX 8.0 base graphics ---------------------------------------------------
# OpenTTD will not start without a base graphics set. The release zip contains
# opengfx-8.0.tar, which goes straight into the binary's baseset/ directory.
mkdir -p "${BASESET}"
if [ -f "${OPENGFX_TAR}" ]; then
  echo "[setup] OpenGFX already present at ${OPENGFX_TAR}, skipping download."
else
  if [ ! -f "${OPENGFX_ZIP}" ]; then
    echo "[setup] downloading OpenGFX 8.0 ..."
    curl -fL "${OPENGFX_URL}" -o "${OPENGFX_ZIP}"
  fi
  echo "[setup] extracting opengfx-8.0.tar into baseset ..."
  # The zip holds opengfx-8.0.tar (plus a license/readme). Pull out just the tar.
  unzip -q -o -j "${OPENGFX_ZIP}" "opengfx-8.0.tar" -d "${BASESET}"
fi

# --- Python toolchain ------------------------------------------------------------
# amaranth (HDL frontend), numpy (golden model maths), pillow + pygame (viewer),
# pytest (test runner). Installed into the user site so no venv is required.
echo "[setup] installing Python dependencies ..."
pip install --user amaranth numpy pillow pytest pygame

echo ""
echo "[setup] done. Quick check:"
echo "  binary: ${OPENTTD_DIR}/openttd.exe"
echo "  opengfx: ${OPENGFX_TAR}"
echo "  run the headless smoke test with: bash scripts/run_headless.sh"

# --- OPTIONAL: yosys + verilator via oss-cad-suite -------------------------------
# The synth/ flow has a self-contained Python NOR lowering (Netlist.to_nor), so the core
# pipeline does NOT require yosys. But the PROPER verilog -> techmap -> NOR synthesis path
# (synth/adder4.ys, driven by synth/yosys_synth.py) DOES run when a full yosys is installed,
# and synth/test_yosys.py then checks its result equivalent to the Python flow. oss-cad-suite
# ships both yosys and verilator.
#
# This was installed and is in use here. Install it the same way (kept OUT of the repo tree,
# the bundle is ~2 GB and the repo may live in a cloud-synced folder):
#
#   OCS_URL=$(curl -sS https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest \
#     | grep browser_download_url | sed 's/.*: "//;s/"//' | grep -i 'windows-x64.*\.exe')
#   curl -fL "$OCS_URL" -o "$HOME/ossbuild/osscad.exe"
#   "/c/Program Files/7-Zip/7z.exe" x "$HOME/ossbuild/osscad.exe" -o"$HOME/ossbuild" -y
#   # -> $HOME/ossbuild/oss-cad-suite/bin/yosys.exe (+ verilator_bin.exe)
#
# synth/yosys_synth.py auto-detects it at $OSS_CAD_SUITE_ROOT, ~/ossbuild/oss-cad-suite,
# ~/oss-cad-suite, C:/oss-cad-suite, or on PATH. On the Windows build, point TEMP at a clean
# dir and add the suite's lib/ to PATH for the bundled DLLs (yosys_synth.prepare_env does this).
# On Linux/macOS, grab the matching oss-cad-suite bundle and put its bin/ on PATH.

# --- OPTIONAL: build OpenTTD from source with CMake ------------------------------
# We did NOT do this here because there is no C/C++ compiler in this environment.
# For reference, the source build a human would run is roughly:
#
#   git clone https://github.com/OpenTTD/OpenTTD vendor/openttd/src
#   cd vendor/openttd/src
#   cmake -B build -DCMAKE_BUILD_TYPE=Release
#   cmake --build build -j
#
# This needs a C++20 compiler plus OpenTTD's dependencies (see its README). The
# resulting binary is a drop-in replacement for the prebuilt one used above.
