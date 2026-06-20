/*
 * norgate_gs metadata. A VERIFIED computing gate (NOT and 2-input NOR) built from
 * OpenTTD track + a block signal, proven in game by poking inputs and watching the
 * output flip. See readme.txt and ../GATE_DESIGN.md (the SOLVED section).
 *
 * The CreateInstance class name (NorProbeMain) matches main.nut, which was
 * developed under the working title "norprobe".
 */
class NorGateGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "norgate"; }
    function GetShortName()     { return "NRGT"; }
    function GetDescription()   { return "Verified NOT / 2-input NOR from track + a block signal, observed via GSVehicle."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-20"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "NorProbeMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(NorGateGS());
