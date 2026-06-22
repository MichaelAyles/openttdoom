/*
 * fibgate_gs metadata. A CLOCK-STEPPED FIBONACCI readout on the proven clocked-gate
 * mechanism (a fork of main_clocked.nut): a self-sustaining clock train + per-edge
 * WaitClockEdge driving a bank of NBITS real block-signal NOT/NOR gate lanes that
 * present the successive Fibonacci terms 1,1,2,3,5,8,13, read back via the company name.
 *
 * Results are read through the COMPANY NAME (rcon companies); GSLog does not relay here.
 * GetName has NO space so it round-trips through openttd.cfg [game_scripts].
 *
 * To run: install main_fib.nut as main.nut and this as info.nut in
 * ~/OneDrive/Documents/OpenTTD/game/fibgate_gs/, set openttd.cfg [game_scripts] first
 * entry to "fibgate =", start ./openttd.exe -D -d script=1, rcon start_ai, poll companies.
 */
class FibGateGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "fibgate"; }
    function GetShortName()     { return "FIBG"; }
    function GetDescription()   { return "Clock-stepped Fibonacci readout on a bank of block-signal NOR gates."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-22"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "FibMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(FibGateGS());
