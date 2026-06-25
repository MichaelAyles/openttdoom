/*
 * fasum_gs metadata. STAGE 2: the FULL-ADDER SUM = parity(a,b,cin) = XOR( XOR(a,b), cin ), as two
 * bridged-XOR stages chained on real trains. XOR1 (the proven xorsum1 6-gate bridged XOR) computes
 * h = a XOR b; XOR2 (a regen XOR where h is read exactly once, fan-out 1) computes s = XOR(h, cin),
 * with the XOR1 output h COUPLED into XOR2's input (the chain link), couplings that cross a lane
 * routed as BRIDGES. nh fan-out 2 is realised by duplicating the NH gate (NHa drives HH, NHb drives
 * Q), so only the NHb->Q coupling needs a bridge (over NHa,HH,P,Y).
 *
 * Truth table s over (a,b,cin) = 000..111 is 0,1,1,0,1,0,0,1 = parity, judged from RAW Y reader x.
 * Readout via company name (short): "FS<Y_SIG> <8 s reader x>" plus per-combo "c<abc> h<x> s<x>".
 */
class FaSumGS extends GSInfo {
    function GetAuthor()        { return "openttdoom"; }
    function GetName()          { return "fasum"; }
    function GetShortName()     { return "FASM"; }
    function GetDescription()   { return "Stage 2: full-adder SUM = parity(a,b,cin), two bridged-XOR stages chained (XOR1 output h coupled into XOR2)."; }
    function GetVersion()       { return 1; }
    function GetDate()          { return "2026-06-25"; }
    function GetAPIVersion()    { return "15"; }
    function MinVersionToLoad() { return 1; }
    function CreateInstance()   { return "FaSumMain"; }
    function GetCategory()      { return "Test"; }
}
RegisterGS(FaSumGS());
