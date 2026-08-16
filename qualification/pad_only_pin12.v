// Candidate eighth top-edge output: decimal L48 lead PIN_12, pad (20,13) z3.
// Vendor route: X14Y9_SLICE4 F -> OMUX12 -> RMUX31@(15,9) ->
// RMUX31@(17,9) -> RMUX25@(20,9) -> RMUX00@(20,13) -> IOMUX03.
module top (input clk, output o_pin12);
  wire q12;
  wire f12;
  (* keep, BEL = "X14Y9_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin12_tff (
    .CLK(clk), .I({q12, 3'b000}), .F(f12), .Q(q12));
  assign o_pin12 = f12;
endmodule
