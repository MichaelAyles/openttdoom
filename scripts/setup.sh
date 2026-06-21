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
# M0 uses the prebuilt binary for convenience and speed. A from-source MSVC build also
# works on this box and is verified, see the "build from source" note at the bottom.
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

# --- OPTIONAL: build OpenTTD from source with MSVC (VERIFIED on this box) ---------
# M0 uses the prebuilt binary for convenience, but OpenTTD 15.3 also builds from source
# here. The box has Visual Studio 2022 (MSVC cl.exe 19.43, C++20), the Windows SDK, vcpkg
# (bundled with VS), CMake and Ninja. MSVC is not on the Git-Bash PATH, it loads via
# vcvars64.bat. The verified recipe (run from a Windows cmd, not Git-Bash):
#
#   call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
#   REM CMake 4.0 rejects cmake_minimum_required < 3.5 (old dep lzo); relax it and have
#   REM vcpkg keep the var through its sanitized per-port build environment:
#   set CMAKE_POLICY_VERSION_MINIMUM=3.5
#   set VCPKG_KEEP_ENV_VARS=CMAKE_POLICY_VERSION_MINIMUM
#   git clone --depth 1 --branch 15.3 https://github.com/OpenTTD/OpenTTD
#   cd OpenTTD
#   cmake -B build -G "Visual Studio 17 2022" -A x64 ^
#     -DCMAKE_TOOLCHAIN_FILE="C:\Program Files\Microsoft Visual Studio\2022\Community\VC\vcpkg\scripts\buildsystems\vcpkg.cmake" ^
#     -DVCPKG_TARGET_TRIPLET=x64-windows-static -DCMAKE_POLICY_VERSION_MINIMUM=3.5
#   cmake --build build --config Release -j 4
#   REM -> build\Release\openttd.exe (revision 15.3).
#
# To RUN the self-built exe it needs the runtime data alongside it (lang\, baseset\, ai\,
# game\): either run "cmake --install build --prefix <dir>" for a complete layout, or copy
# the exe into a dir that already has those (e.g. the prebuilt baseset). The self-built
# binary passes the same M0 headless timing test. This is what unblocks the speed fork.
