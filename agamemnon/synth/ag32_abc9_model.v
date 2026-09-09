// ABC9 technology model for the ordinary AGRV2K four-input logic function.
//
// The four values exactly mirror the shipped conservative AGRV2K timing
// model, `engine/uarch/agrv2k/agrv2k.cc:SLICE_LUT_TO_F_NS`: 0.608, 0.565,
// 0.474, and 0.149 ns for physical alta_slice A/B/C/D -> LutOut.  That model
// records them as maxima from decoded vendor timing data, with no routing,
// clock-skew, IO, speed-grade, PVT selection, margin, or silicon claim.
// Values below are picoseconds, as required by Yosys/ABC9.  The private
// source table is not copied into this public model.
//
// The correspondence is structural: archgen names alta_slice A/B/C/D as
// GENERIC_SLICE I[0]/I[1]/I[2]/I[3], and cells_map.v preserves $lut A[0..3]
// in that I[0..3] order.  Later legal pin/INIT-axis permutations preserve
// function but can change physical input assignment, so ABC9's pin ranking
// is a pre-pack heuristic only, never a final timing assertion.
//
// This is deliberately only the LUT model.  The same recovered library does
// contain ordinary CLK->Q values, but no model here claims the timing or
// legality of the decoded shared-control DFFE forms.  The synthesis hook
// consequently invokes `abc9` without `-dff`: DFF/DFFE legalisation remains
// on the existing path.  AG32_FA is likewise left as the existing black-box
// carry primitive; it is packed into the dedicated CIN/COUT hardware after
// mapping and must never become an ABC9 timing/logic box.

(* abc9_lut = 1, lib_whitebox *)
module AG32_ABC9_LUT4 (
    output O,
    input I0, I1, I2, I3
);
    parameter [15:0] INIT = 16'h0000;

    wire [7:0] s3 = I3 ? INIT[15:8] : INIT[7:0];
    wire [3:0] s2 = I2 ? s3[7:4] : s3[3:0];
    wire [1:0] s1 = I1 ? s2[3:2] : s2[1:0];
    assign O = I0 ? s1[1] : s1[0];

    specify
        (I0 => O) = 608;
        (I1 => O) = 565;
        (I2 => O) = 474;
        (I3 => O) = 149;
    endspecify
endmodule
