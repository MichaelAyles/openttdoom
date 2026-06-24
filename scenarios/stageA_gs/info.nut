/*
 * stageA_gs metadata. A FIXED THREE-GATE CHAIN, DEEPER than norchain's two, proving the
 * fixed signal-free coupling composes past two gates.
 *
 * Network (each gate its own lane, wired by FIXED pure-vertical signal-free spurs, built
 * ONCE per input combo, NO per-gate train re-parked between reads):
 *     g0 = NOR(a, b)         -> n0
 *     g1 = NOR(n0, a)        -> n1      (reads coupling n0 AND primary a)
 *     g2 = NOR(n1)           -> y       (a NOT)
 * Truth table y over (a,b) = 00,01,10,11 is 1,0,1,1, judged from RAW reader x.
 *
 * Same primitive as norchain: a bit is train-presence on a protected block; a reader
 * passes a block signal iff its input block is empty. A passing driver reader is FROZEN
 * on its coupling tile; a signal-free vertical spur joins that tile into the next gate's
 * input block, so the driver's output physically occupies the consumer's input.
 *
 * Readout: the four g2 (output) reader final x are encoded SHORT into the COMPANY NAME,
 * read via "rcon companies". Judge: x > SIGgX (the g2 reader signal x) => output 1.
 *
 * The CreateInstance class name (StageAMain) matches main.nut.
 */
class StageAGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "stageA"; }
    function GetShortName()     { return "STGA"; }
    function GetDescription()   { return "Fixed 3-gate chain g2=NOT(NOR(NOR(a,b),a)), composition past 2 gates."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-24"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "StageAMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(StageAGS());
