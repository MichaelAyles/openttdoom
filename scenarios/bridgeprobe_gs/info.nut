/*
 * bridgeprobe_gs metadata. A minimal probe of the BRIDGE CROSSING primitive (STUCK.md #9):
 * a signal-free vertical coupling spur crosses a perpendicular horizontal reader lane of an
 * INDEPENDENT gate, routed as a BRIDGE (the spur goes OVER the lane). Proves the two nets are
 * ISOLATED: the spur still couples its driver bit through the bridge, and the crossed lane's
 * gate still computes correctly (the bridge did NOT short the lane into the spur block).
 *
 * Probe encodes, into the company name (read via "rcon companies"):
 *   BP <consumerSig> <crossSig> <consumer reader x> <crossed reader x> for a driver=1 case.
 * Judge externally from RAW reader x. The bridge separates the spur and lane tiles into two map
 * tiles in two blocks, so both nets read their true values.
 */
class BridgeProbeGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "bridgeprobe"; }
    function GetShortName()     { return "BPRB"; }
    function GetDescription()   { return "Probe: a signal-free coupling spur crosses an independent reader lane via a BRIDGE; both nets isolated."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-25"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "BridgeProbeMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(BridgeProbeGS());
