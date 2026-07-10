// AG32 ripple-carry slice primitive (front-end techmap target).
//
// Models ONE alta_slice in "ripple" mode (see memory ag32-dense-carry-mechanism / alta_sim.v):
//   pinC = Cin (modeMux=1);  SUM(=LutOut) = A ^ B ^ Cin  (mask hi byte, D=1);
//   COUT = maj(A,B,Cin)      (mask lo byte, DEDICATED HARDWARE -- never routed through the fabric mesh).
// Kept as an instance through synth/abc (read -lib => blackbox) so the CIN/COUT chain survives to the
// second techmap that lowers it to a GENERIC_SLICE (INIT=0x96E8, I[3]=D=1, CIN/COUT bel pins).
(* blackbox *)
module AG32_FA (
    input  A,
    input  B,
    input  CIN,
    output SUM,
    output COUT
);
endmodule
