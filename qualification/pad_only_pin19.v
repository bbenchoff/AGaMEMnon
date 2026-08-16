// Seventh qualified top-edge output: decimal L48 lead PIN_19, pad (17,13) z3.
// The vendor-observed approach is X14Y9 OMUX24 -> X15Y9 RMUX68 ->
// X17Y9 RMUX85 -> X17Y13 RMUX16 -> IOMUX3.
module top (input clk, output o_pin19);
  wire q19;
  wire f19;
  (* keep, BEL = "X14Y9_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin19_tff (
    .CLK(clk), .I({q19, 3'b000}), .F(f19), .Q(q19));
  assign o_pin19 = f19;
endmodule
