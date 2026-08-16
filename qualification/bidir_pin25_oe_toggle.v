// Local self-toggling dynamic-OE witness for L48 PIN_25.
//
// The LUT/DFF uses the already-qualified single direct-feedback site.  Its Q
// feeds the LUT, the LUT computes ~Q for both the D input and F output, and the
// exact-OE packer inserts a transparent presentation LUT at X10Y4_SLICE0 before
// the same X10Y4_OMUX02 -> X0Y4_IOMUX06 corridor as the constant-source A/B.
// This avoids the unqualified external PIN_10 ingress.  Pad data is a hard
// zero: the circuit can only alternate between release and drive-low.
module pin25_oe_toggle(input clk, inout link, output observed);
  (* keep *) reg state = 1'b0;
  (* keep *) wire drive_low = ~state;
  always @(posedge clk)
    state <= drive_low;

  assign link = drive_low ? 1'b0 : 1'bz;
  assign observed = ~link;
endmodule
