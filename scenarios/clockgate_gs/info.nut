/*
 * clockgate_gs metadata. A CLOCK train on a closed loop (sub-goal 1), live gate
 * re-evaluation on the SAME tiles (sub-goal 2), and an attempt at clock-synchronised
 * sampling (sub-goal 3), built on the verified norgate/norchain primitives.
 *
 * Results are read through the COMPANY NAME (rcon companies), since GSLog does not
 * relay reliably to the admin port here.
 *
 * Variants live in this folder; copy the one you want to main.nut and set the
 * CreateInstance name below to match its class:
 *   main_clock.nut   -> class ClockGateMain (sub-goal 1, the clock train)   VERIFIED
 *   main_reeval.nut  -> class ReevalMain    (sub-goal 2, live re-eval)      VERIFIED
 *   main_sync.nut    -> class SyncMain       (sub-goal 3, clock-synced)      PARTIAL (0/3)
 *   main_clocked.nut -> class ClockedMain    (sub-goal 4, reliable clocked)  RELIABLE
 * As shipped, main.nut is a copy of main_clocked.nut, so CreateInstance is ClockedMain.
 *
 * GetName has NO space so it round-trips through openttd.cfg [game_scripts].
 */
class ClockGateGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "clockgate"; }
    function GetShortName()     { return "CLKG"; }
    function GetDescription()   { return "Clock train on a loop, live gate re-eval on the same tiles, and clock-synced sampling."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-21"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "ClockedMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(ClockGateGS());
