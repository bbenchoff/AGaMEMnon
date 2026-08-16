// Candidate decimal L48 lead PIN_11, pad (20,13) z2.
module top (input clk, output o_pin11);
  wire q11;
  wire f11;
  (* keep, BEL = "X14Y9_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin11_tff (
    .CLK(clk), .I({q11, 3'b000}), .F(f11), .Q(q11));
  assign o_pin11 = f11;
endmodule
