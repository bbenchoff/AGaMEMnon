// N5.8C nearest-reachable I2 discriminator: retain the accepted typed
// HWDATA25 endpoint and mandatory first hop, then consume it at the nearest
// strict-graph I2 sink after fixed-site X14Y9_SLICE0.I2 rejected fail-closed.
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
  // this distinct composition moves to nearest reachable X14Y10_SLICE0.I2.
  (* keep, BEL="X14Y10_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    hwdata25_i2_identity(
      .CLK(),
      .I({1'bx, hwdata25, 2'bxx}),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
