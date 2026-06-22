/*
 * register_gs metadata. A CLOCKED 1-BIT REGISTER (memory cell) on trains.
 *
 * The stored bit Q is the PRESENCE of a parked train on a HOLD tile inside a
 * protected block. A parked train persists indefinitely with no further action,
 * which is the memory. Each clock edge an independent reader samples Q (it passes
 * its block signal iff HOLD is empty, so reader-held == Q). A clock-gated WRITE
 * sets Q to a new value, which then persists across subsequent edges.
 *
 * The point being PROVEN: across several clock edges with NO write the read-back Q
 * is identical (the bit HOLDS), and after a clock-gated write Q updates and then
 * HOLDS the new value. Judged from RAW reader-train positions via the company name
 * (rcon companies), since GSLog does not relay reliably here.
 *
 * Built on the verified primitives: the self-sustaining one-way block-signalled
 * clock loop and per-edge WaitClockEdge (scenarios/clockgate_gs/main_clocked.nut,
 * 8/8), the block-signal NOR/NOT read (scenarios/norgate_gs), and the parked-train
 * presence coupling (scenarios/norchain_gs).
 *
 * GetName has NO space so it round-trips through openttd.cfg [game_scripts].
 */
class RegisterInfo extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "register"; }
    function GetShortName()     { return "REGX"; }
    function GetDescription()   { return "Clocked 1-bit register: a parked-train presence bit that holds across clock edges and updates on a clock-gated write."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-22"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "RegisterMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(RegisterInfo());
