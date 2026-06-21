/*
 * computecell_gs metadata. THE FUSION: a NOR cell STAMPED FROM A PLACED NETLIST
 * (scenario_data.nut emitted by place_and_route) that actually COMPUTES in OpenTTD.
 *
 * The stamp geometry is the VERIFIED norgate_gs primitive (a block-signal NOR),
 * parameterised at the placed cell's (x, y) with its input-tap and output tiles read
 * from the placement. No hand-coded gate coordinates: everything is derived from the
 * placement the toolchain emitted.
 */
class ComputeCellGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "computecell"; }
    function GetShortName()     { return "CCEL"; }
    function GetDescription()   { return "Stamps a computing NOR cell from a placed netlist and verifies it via raw reader positions."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-21"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "ComputeCellMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(ComputeCellGS());
