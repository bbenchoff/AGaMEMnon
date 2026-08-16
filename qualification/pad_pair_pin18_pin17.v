// Independence/interference test for the two bonded slots on pad tile
// (18,13): qualified PIN_18 z0 and candidate PIN_17 z3.
module top (input clk, output o_pin18, output o_pin17);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin18 = a;

  wire q17;
  wire f17;
  (* keep, BEL = "X14Y9_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin17_tff (
    .CLK(clk), .I({q17, 3'b000}), .F(f17), .Q(q17));
  assign o_pin17 = f17;
endmodule
