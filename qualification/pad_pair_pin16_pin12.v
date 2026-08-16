// Independence test for candidate PIN_12 and qualified PIN_16.
module top (input clk, output o_pin16, output o_pin12);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin16 = a;

  wire q12;
  wire f12;
  (* keep, BEL = "X14Y9_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin12_tff (
    .CLK(clk), .I({q12, 3'b000}), .F(f12), .Q(q12));
  assign o_pin12 = f12;
endmodule
