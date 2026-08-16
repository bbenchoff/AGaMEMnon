// External PIN_10 control re-buffered at the vendor's X14Y4 slice4 boundary.
//
// The vendor four-link oracle does not route PIN_10 directly to the X10Y4 OE
// source.  It enters X14Y4_SLICE4 on IMUX18, crosses the slice LUT, then leaves
// OMUX14 for X10Y4.  This identity stage tests that single architectural
// distinction while retaining the already-qualified PIN_25 data-low, input,
// readback, presentation-LUT, and six-pip OE corridor composition.
module pin25_oe_vendor_stage(input drive_low, inout link, output observed);
  wire staged;
  (* keep, BEL = "X14Y4_SLICE4", AGRV2K_PIN25_VENDOR_STAGE = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    pin10_vendor_stage(.CLK(), .I({1'b0, drive_low, 2'b00}), .F(staged), .Q());

  assign link = staged ? 1'b0 : 1'bz;
  assign observed = ~link;
endmodule
