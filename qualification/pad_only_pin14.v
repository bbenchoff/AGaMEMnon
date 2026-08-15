// Candidate fourth top-edge output pad: PIN_14, pad tile (19,13) slot z2.
//
// Use the vendor-faithful one-slice TFF presentation needed to launch on
// OMUX45. The staged composition pins the measured RMUX19@(19,9) -> RMUX24
// pad-feed hop and excludes the empty-codeword RMUX25@(19,12) -> RMUX00
// alternative.
module top (input clk, output o_pin14);
  // Vendor-faithful TFF presentation in one physical slice: Q feeds input D,
  // INIT=~D drives F, and the register captures F. At this exact BEL the
  // vendor-output presentation puts F on the required OMUX45 and Q on the
  // local feedback OMUX46.
  wire q14;
  wire f14;
  (* keep, BEL = "X14Y9_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin14_tff (
    .CLK(clk), .I({q14, 3'b000}), .F(f14), .Q(q14));
  assign o_pin14 = f14;
endmodule
