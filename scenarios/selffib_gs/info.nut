/*
 * selffib_gs metadata. A SELF-FEEDING FIBONACCI on OpenTTD trains.
 *
 * Two multi-bit registers a, b are HELD in track (each bit = a parked train on a HOLD tile,
 * the register_gs / toggle_gs cell). Each clock edge: read a and b from the held registers
 * (RAW reader x per bit); compute next = a + b with a REAL block-signal NOR full adder (every
 * sum bit and carry is the raw PASS/HOLD outcome of a block-signal NOR gate, composed in the
 * NOR-only full-adder form, NOR being universal); SHIFT a <- b, b <- next (GS-mediated write,
 * the honest boundary); read out next. Initialised a=0, b=1, so the output is 1,1,2,3,5,8,13
 * produced by the machine feeding its OWN held state back through the gates, with NO
 * Fibonacci/sequence array anywhere.
 *
 * Built on the verified primitives: the hardened one-way block-signalled clock launch
 * (clockgate main_clocked / register_gs / toggle_gs LaunchClockConfirmed), the block-signal
 * NOR read (norgate_gs), the clocked parked-train register (register_gs, RG 11100), and the
 * self-feeding toggle (toggle_gs, TG 010101, next = NOT(held Q) from a real gate).
 *
 * Readout "FF <t0> <t1> ..." (the output terms), judged from RAW per-edge reads via the
 * company name (rcon companies); GSLog does not relay reliably here. Reliability compounds
 * (register x adder x shift x clock), so this is low-yield by design: it reports every per-edge
 * readout and exactly how many terms self-fed before a read failed.
 *
 * GetName has NO space so it round-trips through openttd.cfg [game_scripts].
 */
class SelfFibInfo extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "selffib"; }
    function GetShortName()     { return "SFBX"; }
    function GetDescription()   { return "Self-feeding Fibonacci: next = a + b from two held multi-bit registers, computed by a real block-signal NOR full adder (sum bits read at raw positions), shifted back; no sequence array."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-24"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "FibMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(SelfFibInfo());
