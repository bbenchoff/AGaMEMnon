// N5.8C graph-legal I2 discriminator: retain the accepted typed HWDATA25
// endpoint and mandatory first hop, then consume it at the nearest Y9 I2 sink
// that also has a directed path to the fixed PIN18 observation pad.
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

  // INIT=F0F0 is identity on I2. I0 and I1 are accepted at X14Y9_SLICE0;
  // X15Y9_SLICE2 is the smallest one-tile Y9 move with input/output closure.
  (* keep, BEL="X15Y9_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    hwdata25_i2_identity(
      .CLK(),
      .I({1'bx, hwdata25, 2'bxx}),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
