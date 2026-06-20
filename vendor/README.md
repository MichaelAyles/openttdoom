# vendor/

Pulled dependencies. Everything here is downloaded by `scripts/setup.sh` and is
gitignored (it is large and reproducible, not source we maintain).

- `openttd/` the prebuilt OpenTTD 15.3 win64 binary plus the OpenGFX 8.0 base set in
  its `baseset/`. We use the prebuilt binary because this environment has no C++
  compiler. See `scripts/setup.sh` for the source-build alternative.
- `chip8/roms/` the Timendus chip8-test-suite reference ROMs the golden model is
  checked against (`2-ibm-logo`, `3-corax+`, `4-flags`).
- `doom/` reference only (the look and the 256-colour palette), not pulled this run.

Run `bash scripts/setup.sh` to populate this directory.
