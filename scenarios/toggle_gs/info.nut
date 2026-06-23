/*
 * toggle_gs metadata. A SELF-FEEDING 1-BIT TOGGLE (T flip-flop / divide-by-2) on trains.
 *
 * This is the clocked 1-bit register (scenarios/register_gs) with the external write
 * schedule removed and replaced by genuine self-feeding: each clock edge the next stored
 * bit is NOT(held Q), where NOT(held Q) is produced by a REAL block-signal NOT gate that
 * reads the machine's OWN held state from a RAW reader position. The register value steps
 * 0,1,0,1,... purely because each next value came from the NOT gate's raw output fed by the
 * held bit, with NO toggle/Fibonacci array driving the writes. The write-BACK is GS-mediated
 * (build/park or remove the HOLD train per the gate's raw-read result), the honest boundary.
 *
 * Built on the verified primitives: the self-sustaining one-way block-signalled clock loop
 * and per-edge WaitClockEdge (clockgate_gs/main_clocked, 8/8), the block-signal NOR/NOT read
 * (norgate_gs), and the clocked parked-train register (register_gs, RG 11100).
 *
 * Readout "TG 010101" (MSB = the bit held entering edge 0), judged from RAW reader x via the
 * company name (rcon companies), since GSLog does not relay reliably here.
 *
 * GetName has NO space so it round-trips through openttd.cfg [game_scripts].
 */
class ToggleInfo extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "toggle"; }
    function GetShortName()     { return "TGGX"; }
    function GetDescription()   { return "Self-feeding 1-bit toggle (T flip-flop): next = NOT(held Q) from a real block-signal NOT gate reading the held register bit; no external schedule."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-23"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "ToggleMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(ToggleInfo());
