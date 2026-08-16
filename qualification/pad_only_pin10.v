// Candidate decimal L48 lead PIN_10, pad (20,13) z1.
module top (input clk, output o_pin10);
  wire q10;
  wire f10;
  (* keep, BEL = "X14Y9_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin10_tff (
    .CLK(clk), .I({q10, 3'b000}), .F(f10), .Q(q10));
  assign o_pin10 = f10;
endmodule
