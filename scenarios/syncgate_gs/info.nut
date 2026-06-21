/*
 * syncgate metadata. A PURE TRACK-SIGNAL clock interlock + output register: the
 * clock train's occupancy of a clock block physically releases a waiting reader
 * once per lap, with NO GameScript in the per-edge timing path. The GS builds the
 * structure and reads the final result (positions / per-edge samples) via the
 * company name, but does NOT poll the clock or dispatch the reader.
 *
 * Builds on the verified primitives: scenarios/norgate_gs (block signal reads
 * occupancy, BuildSignal(tile,front) facing, dead-end rule) and
 * scenarios/clockgate_gs (the clock train on a closed loop, period ~520 ticks).
 *
 * The CreateInstance class name (SyncGateMain) matches main.nut.
 */
class SyncGateGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "syncgate"; }
    function GetShortName()     { return "SYNG"; }
    function GetDescription()   { return "Pure track-signal clock interlock + output register, observed via GSVehicle positions."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-21"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "SyncGateMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(SyncGateGS());
