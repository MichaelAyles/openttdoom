/*
 * xorbridge_gs metadata. STAGE 2 application of the bridge crossing primitive: a reconvergent
 * NOR network whose coupling spur is forced NON-PLANAR (it crosses an intervening root's reader
 * lane) and routes that crossing as a BRIDGE. Computes the half-adder CARRY = a AND b:
 *     g0 = NOR(a) -> na      g1 = NOR(b) -> nb      g2 = NOR(na,nb) = AND(a,b)
 * Unlike stageBcarry (g2 placed BETWEEN its drivers, planar, no crossing), here g2 is BELOW both
 * roots so g0's coupling spur to g2 must CROSS g1's reader lane. That crossing is a BRIDGE: the
 * spur goes OVER g1's lane, keeping g0->g2 coupled while leaving g1's lane isolated. Proves the
 * bridge primitive composes into real reconvergent logic.
 *
 * Truth table c over (a,b)=00,01,10,11 is 0,0,0,1 = AND, judged from RAW g2 reader x (x>SIG=>1).
 * Readout via company name (short): "XB s<G2_SIG> <c00> <c01> <c10> <c11> b<bridge built 0/1>".
 */
class XorBridgeGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "xorbridge"; }
    function GetShortName()     { return "XBRG"; }
    function GetDescription()   { return "Stage 2: reconvergent AND with a non-planar coupling spur crossing an intervening lane via a BRIDGE."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-25"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "XorBridgeMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(XorBridgeGS());
