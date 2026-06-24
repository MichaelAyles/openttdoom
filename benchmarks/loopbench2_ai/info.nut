class LoopBench2 extends AIInfo {
	function GetAuthor()      { return "openttdoom"; }
	function GetName()        { return "LoopBench2"; }
	function GetShortName()   { return "LPB2"; }
	function GetDescription() { return "Circulating loops WITH a junction siding, to exercise per-train YAPF."; }
	function GetVersion()     { return 1; }
	function GetDate()        { return "2026-06-24"; }
	function CreateInstance() { return "LoopBench2"; }
	function GetAPIVersion()  { return "14"; }
}

RegisterAI(LoopBench2());
