/*
 * xorsum1_gs metadata. STAGE 1: the half-adder SUM bit (a XOR b) as the SAME 6-gate NOR network
 * as stageB, but with the reconvergent output coupling (g3 -> g4) routed as a BRIDGE instead of
 * stageB's flaky far-push east. This is the reliability fix: stageB's far-pushed g3 freeze block
 * settled only ~57% of the time; here g3 freezes CLOSE and the g3->g4 spur bridges over the two
 * intervening lanes (the bridgeprobe / xorbridge primitive), so the merged-block flake is removed.
 *
 * Network (merge-free, fan-out driver NOR(a,b) duplicated as g0a,g0b):
 *     g0a = NOR(a,b) -> n1a    g0b = NOR(a,b) -> n1b
 *     g1  = NOR(a,n1a) -> n2   g2  = NOR(b,n1b) -> n3
 *     g3  = NOR(n2,n3) -> n4   g4  = NOR(n4) -> y
 * Truth table y over (a,b) = 00,01,10,11 is 0,1,1,0 = XOR, judged from RAW g4 reader x.
 *
 * Readout (short company name): "XS1 s<F_SIG> <y00> <y01> <y10> <y11> b<all bridges built 0/1>".
 */
class XorSum1GS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "xorsum1"; }
    function GetShortName()     { return "XS1G"; }
    function GetDescription()   { return "Stage 1: half-adder SUM = a XOR b, the reconvergent g3->g4 output coupling routed as a BRIDGE (reliability fix for stageB's far-push)."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-25"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "XorSum1Main"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(XorSum1GS());
