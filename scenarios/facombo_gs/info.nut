/*
 * facombo_gs metadata. The SINGLE-COMBO full adder: build ONE combo's worth of network per run
 * (the bridged SUM = parity + the majority CARRY for one (a,b,cin)), about 16 gates + 6 bridges,
 * NOT the 8-copy 48-bridge mega-build. The combo 0..7 is selected by the `combo` GS setting
 * (GSController.GetSetting("combo")), set per run via openttd.cfg [game_scripts.facombo]. Reuses the
 * hardened fulladder_gs gate/bridge/freeze code VERBATIM, just builds one band instead of eight.
 *
 * Truth tables over (a,b,cin)=000..111, judged from RAW reader x:
 *   sum  = parity   = 0,1,1,0,1,0,0,1   (Y reader x > Y_SIG=50)
 *   cout = majority = 0,0,0,1,0,1,1,1   (gm reader x > GM_SIG=40)
 * Readout via the short company name: "FA<Y_SIG> <sum x>" and "FC<GM_SIG> <cout x>" plus per-combo
 * "c<abc> s<x> m<x>". Nothing computed in Squirrel; the operator judges raw x.
 */
class FaComboGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "facombo"; }
    function GetShortName()     { return "FACB"; }
    function GetDescription()   { return "Single-combo 1-bit full adder: build ONE selectable (a,b,cin) band, bridged SUM (parity) next to majority CARRY, read from raw reader x."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-26"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "FaComboMain"; }
    function GetCategory()      { return "Test"; }
    function GetSettings() {
        AddSetting({name = "combo",
                    description = "which (a,b,cin) input combo to build, 0..7 = 000..111",
                    min_value = 0, max_value = 7, easy_value = 0, medium_value = 0,
                    hard_value = 0, custom_value = 0, flags = CONFIG_INGAME});
    }
}
RegisterGS(FaComboGS());
