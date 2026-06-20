/*
 * openttdoom GameScript metadata (GSInfo).
 *
 * This registers the script with OpenTTD so it shows up in the GameScript list.
 * The real work is in main.nut. See readme.txt for how to install and run this.
 *
 * Targeted at the GS API shipped with OpenTTD 15.x (vendor/openttd here is
 * 15.3, whose game/ dir ships compat_14.nut, so the live API version is "15").
 */

class OpenttdoomGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "openttdoombuilder"; }
    function GetShortName()     { return "OTDM"; }   // 4 chars, must be unique
    function GetDescription() {
        return "Stamps an openttdoom logic design (NOR tiles, routed track, "
             + "a clock train and signal pads) from a baked scenario data table.";
    }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-20"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "OpenttdoomMain"; }
    function GetCategory()      { return "Scenario"; }
}

RegisterGS(OpenttdoomGS());
