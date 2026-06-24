/*
 * stageBcarry_gs metadata. The half-adder CARRY bit (a AND b) as a FIXED 3-gate NOR network
 * on trains, the companion to the stageB SUM (XOR). Carry = AND(a,b) = NOR(NOT a, NOT b):
 *     g0 = NOR(a) -> na        (NOT a)
 *     g1 = NOR(b) -> nb        (NOT b)
 *     g2 = NOR(na, nb) -> c     (reconvergent fan-in)
 * Truth table c over (a,b) = 00,01,10,11 is 0,0,0,1 = AND, judged from RAW reader x.
 *
 * The reconvergence g2 = NOR(na, nb) is placed BETWEEN its two drivers: g0 directly above
 * (spur DOWN), g1 directly below (spur UP), so both fixed signal-free coupling spurs are short
 * and adjacent. Built ONCE per combo, no per-gate train re-parked between reads.
 *
 * The CreateInstance class name (StageBCarryMain) matches main.nut.
 */
class StageBCarryGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "stageBcarry"; }
    function GetShortName()     { return "STBC"; }
    function GetDescription()   { return "Fixed half-adder CARRY = a AND b as a 3-gate NOR network on trains."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-24"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "StageBCarryMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(StageBCarryGS());
