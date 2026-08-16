// Sixth qualified top-edge output: decimal L48 lead PIN_17, pad (18,13) z3.
// The vendor-observed approach is X14Y9 OMUX24 -> X15Y9 RMUX68 ->
// X18Y9 RMUX85 -> X18Y13 RMUX16 -> IOMUX3.
module top (input clk, output o_pin17);
  wire q17;
  wire f17;
  (* keep, BEL = "X14Y9_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin17_tff (
    .CLK(clk), .I({q17, 3'b000}), .F(f17), .Q(q17));
  assign o_pin17 = f17;
endmodule
