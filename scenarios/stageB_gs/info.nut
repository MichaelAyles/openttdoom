/*
 * stageB_gs metadata. A FIXED HALF-ADDER as a NOR network on trains: the SUM bit (a XOR b)
 * as a 6-gate fixed network, proving fan-out and reconvergent fan-in compose past the
 * 2-gate norchain and the 3-gate stageA chain.
 *
 * SUM = a XOR b, built merge-free by DUPLICATING the fan-out driver (each gate drives exactly
 * one consumer block, the proven norchain coupling):
 *     g0a = NOR(a, b) -> n1a       g0b = NOR(a, b) -> n1b
 *     g1  = NOR(a, n1a) -> n2      g2  = NOR(b, n1b) -> n3
 *     g3  = NOR(n2, n3) -> n4      g4  = NOR(n4) -> y
 * Truth table y over (a,b) = 00,01,10,11 is 0,1,1,0 = XOR, judged from RAW reader x.
 *
 * Every gate has its OWN lane, wired by FIXED pure-vertical signal-free coupling spurs
 * (norchain), built ONCE per input combo. No per-gate train is re-parked between reads.
 * The reconvergence g3=NOR(n2,n3) puts g3 BETWEEN its two drivers (g1 above, g2 below) so
 * both coupling spurs are short and adjacent; the g3->g4 output spur is pushed to a far-east
 * column kept clear of the intervening lanes.
 *
 * Readout: the four g4 (output) reader final x encoded SHORT into the COMPANY NAME, read via
 * "rcon companies". Judge: x > SIG (g4 reader signal x) => output 1.
 *
 * The CreateInstance class name (StageBMain) matches main.nut.
 */
class StageBGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "stageB"; }
    function GetShortName()     { return "STGB"; }
    function GetDescription()   { return "Fixed half-adder SUM = a XOR b as a 6-gate NOR network on trains."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-24"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "StageBMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(StageBGS());
