# next-steps.md

Handoff for resuming openttdoom. Written at commit `3a35735` (72 commits, all pushed). Read this,
then `STATUS.md` (what works), then `STUCK.md` #9 (the full in-game saga), then come back here.

## Where we are (one paragraph)

The architecture for a train-built computer is COMPLETE and proven in game: fixed NOR networks plus rail
BRIDGES compose arbitrary logic on real OpenTTD trains, every result judged from raw train positions. The
capstone is a **1-bit FULL ADDER that reads a clean 8/8 truth table** (`sum=parity`, `cout=majority`),
verified by the orchestrator's own runs (`scenarios/facombo_gs/`, see `truth_table.log`). Every reliability
axis that blocked it is closed: clock launch (10/10), dispatch race (deterministic placement), the
reconvergent-read flake (~92% bridged XOR), and the heavy-combo reader stall (the occupancy guard). What is
left is NOT a research unknown, it is reliability at SCALE.

## The single most important thing to understand

**The wall now is COMPOUNDING, not capability.** A large single-run circuit multiplies many ~92 to 99
percent per-dispatch reliabilities, so the 8-combo full-adder MEGA-build (48 bridges, ~128 gates) times out
around 5/8 before finishing. The breakthrough that beats this is **single-combo runs**: build ONE input
combo's worth (~16 gates + 6 bridges) per fresh server, read it, and the UNION of the runs is the truth
table. That is exactly how the full adder reads 8/8. Any next circuit should be built and read this way, not
as one giant single run.

## Next steps, in priority order

1. **Multi-bit ripple adder (the "it scales" proof).** Tile the 1-bit full adder into a 2-bit, then 4-bit,
   ripple adder (carry-out of bit N into carry-in of bit N+1), computed per-combo via the single-combo
   approach (each operand pair a small reliable run, union = the result table). This proves the datapath
   TILES, the real "it is a computer" claim. Reuse `scenarios/facombo_gs/` (one combo per run) and chain the
   carry physically (the cout reader's frozen position couples into the next bit's cin tap, the norchain
   coupling). Start with 2-bit, a handful of operand pairs, judged from raw positions.

2. **Reduce the compounding (the real enabler for anything bigger).** Three independent levers:
   - **Bridge-build b1 reliability.** The intermittent `b0` (a bridge fails its `IsBridgeTile` both-ends
     check) is the most damaging residual at scale. Diagnose the ROOT cause (ramp tile not truly empty? the
     under-rail removed by the build? a transient command-queue failure?) rather than adding more retries.
     `scenarios/facombo_gs/main.nut::BuildOneBridge` and `xorsum1_gs`.
   - **Fewer gates/bridges per circuit.** Smarter layouts (better planarization so fewer spurs cross, gate
     sharing). The software router (`place_and_route/`) already minimises crossings, mine it.
   - **Speed.** The OpenTTD speed fork is ~3x on a bare map; the per-train pathfinding lever was a DEAD END
     (YAPF is never called on fixed PBS rings, `docs/speed_fork.md`). The real per-tick floor is the vehicle
     controller + signal resolution. A faster substrate makes every run faster and bigger circuits viable.

3. **Pure-hardware feedback (the one genuine remaining PRIMITIVE).** The register and the self-feeding
   toggle work, but their write-BACK is GameScript-mediated. A pure track-signal feedback loop with NO GS in
   the timing path hits an OpenTTD reservation-coupling (the "syncgate" blocker, STUCK.md #1). Solving it =
   a fully self-contained sequential element. This is the last real research item.

4. **Toward the actual machine (long horizon, be honest).** A full CHIP-8 / raycaster is thousands of gates,
   compounding-bound at a scale that will NOT close via the current per-combo-copy, GS-dispatched approach.
   The path needs the speed fork pushed much further AND a fundamentally more deterministic or parallel build
   (or accepting per-combo/union verification rather than a single clean run). This is the multi-month
   roadmap in `README.md`, not a single-session target. Do not pretend a single clean run of the whole
   machine is near, it is not, and that is fine, the architecture is what was unknown and it is now proven.

## Operational rules (these cost real time when ignored)

- **ONE OpenTTD at a time.** NEVER run two `openttd` / `run_fixed` / `run_facombo` at once. Each does
  `taskkill //F //IM openttd.exe` at its boundaries, so a leftover zombie kills the live run and it looks
  like a "GS reload / crash" (the company name resets to "<GS> build"). Hard-kill all stray python+openttd
  before every run; SERIALISE in-game work. A whole workflow burned hours on this self-inflicted instability.
- **Verify every agent claim yourself from RAW POSITIONS.** Build agents overclaimed repeatedly (a "5/5
  fixed" was 4/5; "union 8/8" hid that no single run closed; "dispatch nil" was "rare"). Re-run the headline
  on fresh sole-process servers and judge from the reader x in the company name, never the GS's own pass/fail.
- **Long agents fail at the structured-output wrap-up** (after ~200 to 600 tool calls) but the WORK is
  usually sound. Recover from disk: read the modified `.nut` + the `scenarios/*/*.log` they wrote, and the
  agent transcript, then verify yourself. Do not re-run the whole thing.
- **`run_fixed.py` prefix gotcha:** match the RESULT line, not the build status. `--prefix "FA"` matches the
  early "FA build" status and bails in 4s; use the final-line prefix (`"FA5"`, `"XS1 s"`) and a generous
  `--timeout` (single combo ~11 min, the 8-combo full adder ~46 min).
- The GS `combo` config setting does NOT apply on this rig (dedicated-server newgame). `run_facombo.py`
  selects the combo by rewriting a `COMBO_SEL` source constant per run instead.

## The map (key files and commands)

- `scenarios/facombo_gs/` + `tools/run_facombo.py --all` : the single-combo full adder (the capstone, 8/8).
  `truth_table.log` is the evidence.
- `scenarios/xorsum1_gs/` : the bridged XOR (~92%), home of the proven reconvergent fixes (RunG3Freeze with
  the widened coupling block + pin + the egress-stall rebuild-on-stuck).
- `scenarios/bridgeprobe_gs/`, `xorbridge_gs/` : the BRIDGE crossing primitive + recipe (ramp tiles EMPTY,
  under-tile carries the lane, IsBridgeTile-verify, demolish-and-rebuild).
- `scenarios/clockgate_gs/main_clocked.nut` : the proven launch hardening (NudgeEgress = one
  StartStopVehicle per settle, movement-verified, the model reused for every reader egress fix).
- `scenarios/stageB_gs`, `stageBcarry_gs`, `fulladder_cout_gs` : the half-adder XOR/AND and the majority
  carry (8/8).
- `tools/ottd_admin.py` : rcon + the company-name readout (GSLog does not relay on this rig).
- `STUCK.md` #9 (UPDATEs 1 to 9) : the entire composition -> bridge -> compounding -> 8/8 story.
- Memory (loaded each session): `always-send-it-never-stop`, `verify-claims-yourself`,
  `never-overlap-openttd-runs`. They encode the working style above.

## First move on resume

Kill any stray processes, then reproduce the capstone yourself to re-ground:
`python tools/run_facombo.py --all` (sole process), confirm the 8/8 truth table from raw positions. Then
start step 1 (the 2-bit ripple) as single-combo runs.
