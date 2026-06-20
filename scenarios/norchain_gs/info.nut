/*
 * norchain_gs metadata. A TWO-GATE CHAIN that computes OR(a,b) = NOT(NOR(a,b)),
 * proving gate composition: gate 1 (a 2-input NOR of primary inputs a,b) feeds its
 * output into gate 2 (a NOT, i.e. a one-input NOR), so gate2 = NOT(NOR(a,b)) = OR.
 *
 * Built entirely from OpenTTD track + block signals + parked trains, observed by
 * where reader trains stop (GSVehicle.GetLocation). Results are encoded into the
 * COMPANY NAME and read via "rcon companies", since GSLog does not relay reliably.
 *
 * The CreateInstance class name (NorChainMain) matches main.nut.
 */
class NorChainGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "norchain"; }
    function GetShortName()     { return "NCHN"; }
    function GetDescription()   { return "Two-gate chain OR(a,b) = NOT(NOR(a,b)), composition proven in OpenTTD."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-20"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "NorChainMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(NorChainGS());
