class LoopBench extends AIInfo {
	function GetAuthor()      { return "openttdoom"; }
	function GetName()        { return "LoopBench"; }
	function GetShortName()   { return "LPBN"; }
	function GetDescription() { return "Builds rail loops and spawns N trains to benchmark the per-train tick."; }
	function GetVersion()     { return 1; }
	function GetDate()        { return "2026-06-21"; }
	function CreateInstance() { return "LoopBench"; }
	function GetAPIVersion()  { return "14"; }

	function GetSettings() {
		AddSetting({name = "num_trains", description = "trains per loop", min_value = 1, max_value = 400, easy_value = 40, medium_value = 40, hard_value = 40, custom_value = 40, flags = AICONFIG_INGAME});
	}
}

RegisterAI(LoopBench());
