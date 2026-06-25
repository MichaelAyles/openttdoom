/*
 * fulladder_gs metadata. STAGE 3: the COMPLETE 1-bit FULL ADDER on real trains. Each combo band
 * holds BOTH the bridged SUM network (sum = parity(a,b,cin), the fasum two-stacked-XOR with the
 * hardened bridge build) and the majority CARRY network (cout = majority(a,b,cin), the proven
 * fulladder_cout 4-lane NOR network), read together per combo over all 8 combos.
 *
 * Truth tables over (a,b,cin)=000..111, judged from RAW reader x:
 *   sum  = parity   = 0,1,1,0,1,0,0,1   (Y reader x > Y_SIG=50)
 *   cout = majority = 0,0,0,1,0,1,1,1   (gm reader x > GM_SIG=40)
 * Readouts via the short company name: "FA<Y_SIG> <8 sum x>" and "FC<GM_SIG> <8 cout x>" plus
 * per-combo "c<abc> s<x> m<x>". Nothing computed in Squirrel; the operator judges raw x.
 */
class FullAdderGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "fulladder"; }
    function GetShortName()     { return "FADD"; }
    function GetDescription()   { return "Stage 3: complete 1-bit full adder, bridged SUM (parity) next to majority CARRY, both read per combo over all 8 combos."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-25"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "FullAdderMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(FullAdderGS());
