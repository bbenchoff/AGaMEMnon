// Match the vendor's left-edge output primitive: Q feeds the LUT and the
// combinational F output drives the pad.  The physical build sets
// AGAMEMNON_VENDOR_OUT_SLICE to the pad corridor's exact source slice.
module top(input clk, output o);
  reg q = 1'b0;
  always @(posedge clk)
    q <= ~q;
  assign o = ~q;
endmodule
