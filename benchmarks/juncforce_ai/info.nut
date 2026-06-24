class JuncForce extends AIInfo {
	function GetAuthor()      { return "openttdoom"; }
	function GetName()        { return "JuncForce"; }
	function GetShortName()   { return "JNCF"; }
	function GetDescription() { return "Trains routed through a junction with no near safe tile, forcing per-train YAPF."; }
	function GetVersion()     { return 1; }
	function GetDate()        { return "2026-06-24"; }
	function CreateInstance() { return "JuncForce"; }
	function GetAPIVersion()  { return "14"; }
}

RegisterAI(JuncForce());
