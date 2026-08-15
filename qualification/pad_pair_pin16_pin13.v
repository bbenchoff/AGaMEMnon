// Shared-source composition for PIN_16 z0 and PIN_13 z3.
// Both pads consume the same silicon-qualified RMUX55 -> RMUX08 feed, so one
// ring deliberately fans out from that feeder to both IOMUX consumers.
module top (input clk, output o_pin16, output o_pin13);
  wire q13;
  wire f13;
  (* keep, BEL = "X14Y9_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1)) shared_tff (
    .CLK(clk), .I({q13, 3'b000}), .F(f13), .Q(q13));
  assign o_pin16 = f13;
  assign o_pin13 = f13;
endmodule
