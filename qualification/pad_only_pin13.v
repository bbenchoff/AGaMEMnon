// Fifth qualified top-edge output: physical decimal L48 lead PIN_13, slot z3.
// The exact X14Y9 presentation launches F on OMUX30 into the PIN_16-qualified
// RMUX61 -> RMUX55 -> RMUX08 feed; only the final IOMUX consumer changes.
module top (input clk, output o_pin13);
  wire q13;
  wire f13;
  (* keep, BEL = "X14Y9_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) pin13_tff (
    .CLK(clk), .I({q13, 3'b000}), .F(f13), .Q(q13));
  assign o_pin13 = f13;
endmodule
