// N5.8D graph-legal I3 discriminator: retain the accepted typed HWDATA25
// endpoint, mandatory first hop, I2-qualified slice site, and observation
// route, then change only the LUT terminal from I2 to I3.
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

  // INIT=FF00 is identity on I3. X15Y9_SLICE2 and its F-output route are
  // already qualified by N5.8C; this candidate changes only I2 to I3.
  (* keep, BEL="X15Y9_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    hwdata25_i3_identity(
      .CLK(),
      .I({hwdata25, 3'bxxx}),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
