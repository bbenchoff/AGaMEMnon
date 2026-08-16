// Independence test across pad tiles: qualified PIN_16 and candidate PIN_19.
module top (input clk, output o_pin16, output o_pin19);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin16 = a;

  wire q19;
  wire f19;
  (* keep, BEL = "X14Y9_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin19_tff (
    .CLK(clk), .I({q19, 3'b000}), .F(f19), .Q(q19));
  assign o_pin19 = f19;
endmodule
