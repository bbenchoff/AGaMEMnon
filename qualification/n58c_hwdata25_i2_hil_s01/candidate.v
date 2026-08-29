// N5.8C alternate-terminal discriminator: retain the accepted typed HWDATA25
// endpoint and fixed LUT site, but consume it on ordinary input I2 instead of
// the silicon-qualified I0 and I1 terminals.
(* top *)
module top(output observed);
  wire hwdata25;
  wire observed_lut;

  (* keep,
     AGRV2K_MCU_ENDPOINT_INTERFACE="HWDATA",
     AGRV2K_MCU_ENDPOINT_LANE=25,
     AGRV2K_MCU_ENDPOINT_MODE="DIRECT_FABRIC_INPUT",
     AGRV2K_MCU_ENDPOINT_VERSION=1 *)
  MCU_DIN mcu_hwdata25(.DIN(hwdata25));

  // INIT=F0F0 is identity on I2. I0 and I1 are accepted at this same site;
  // the endpoint, mandatory first hop, and output route remain fixed.
  (* keep, BEL="X14Y9_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    hwdata25_i2_identity(
      .CLK(),
      .I({1'bx, hwdata25, 2'bxx}),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
