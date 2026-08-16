// Same-tile independence test for decimal L48 leads PIN_10 and PIN_11.
module top (input clk, output o_pin10, output o_pin11);
  wire q10, f10;
  (* keep, BEL = "X14Y9_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin10_tff (
    .CLK(clk), .I({q10, 3'b000}), .F(f10), .Q(q10));
  assign o_pin10 = f10;
  assign o_pin11 = f10;
endmodule
