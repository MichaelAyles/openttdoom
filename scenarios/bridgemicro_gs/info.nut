class BridgeMicroGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "bridgemicro"; }
    function GetShortName()     { return "BMIC"; }
    function GetDescription()   { return "Micro: find the exact recipe to build a length-3 N-S rail bridge over a perpendicular rail tile."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-25"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "BridgeMicroMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(BridgeMicroGS());
