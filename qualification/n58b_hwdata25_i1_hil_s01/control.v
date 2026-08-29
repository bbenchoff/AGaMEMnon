// Route-matched constant-low control for the N5.8B HWDATA25 I1 discriminator.
(* top *)
module top(output observed);
  wire observed_lut;

  (* keep, BEL="X14Y9_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0000), .FF_USED(1'b0))
    constant_low(
      .CLK(),
      .I(4'bxxxx),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
