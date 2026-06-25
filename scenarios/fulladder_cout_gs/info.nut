/*
 * fulladder_cout_gs metadata. The FULL-ADDER CARRY-OUT cout = majority(a,b,cin) as a fixed NOR
 * network on trains. cout = NOR3( NOR(a,b), NOR(a,cin), NOR(b,cin) ) (verified exhaustively).
 *
 * Three ROOT lanes each read two primary taps (NOR(a,b), NOR(a,cin), NOR(b,cin)); each is frozen
 * on its coupling tile when it passes and a signal-free spur couples it into the final gate gm's
 * input block. gm is a 3-input NOR (its protected block straddles the three root coupling tiles):
 * gm's reader passes iff all three root couplings are absent, i.e. cout = NOR3(...) = majority.
 *
 * Truth table cout over (a,b,cin) = 000..111 is 0,0,0,1,0,1,1,1 = majority, judged from RAW gm
 * reader x (x > GM_SIG => cout 1). Every gate built ONCE per input combo on its own lane, wired by
 * FIXED signal-free coupling spurs; the eight combos are SEPARATE physical copies; NO per-gate
 * coupling train re-parked between reads (0 SellVehicle). Outputs from RAW reader x only.
 *
 * Readout via the company name (kept short for the ~31-char limit): "FC40 <c000> <c001> <c010>
 * <c011> <c100> <c101> <c110> <c111>", the eight gm reader final x. Judge: x > 40 (GM_SIG) => cout 1.
 */
class FullAdderCoutGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "fulladdercout"; }
    function GetShortName()     { return "FACO"; }
    function GetDescription()   { return "Full-adder carry-out cout = majority(a,b,cin) as a fixed NOR network on trains."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-24"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "FullAdderCoutMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(FullAdderCoutGS());
