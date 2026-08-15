// Independence/interference test for PIN_16 z0 and candidate PIN_14 z2.
// Both outputs share pad tile (19,13) and config tile (18,13). PIN_16 uses its
// ordinary two-stage ring; PIN_14 uses the vendor-faithful one-slice TFF whose
// F output launches on the measured OMUX45 approach.
module top (input clk, output o_pin16, output o_pin14);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin16 = a;
  wire q14;
  wire f14;
  (* keep, BEL = "X14Y9_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin14_tff (
    .CLK(clk), .I({q14, 3'b000}), .F(f14), .Q(q14));
  assign o_pin14 = f14;
endmodule
