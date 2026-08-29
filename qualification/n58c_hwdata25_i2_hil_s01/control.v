// Route-matched constant-low control for the N5.8C graph-legal I2 test.
(* top *)
module top(output observed);
  wire observed_lut;

  (* keep, BEL="X15Y9_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0000), .FF_USED(1'b0))
    constant_low(
      .CLK(),
      .I(4'bxxxx),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
