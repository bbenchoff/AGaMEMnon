// N5.8A silicon discriminator: one typed HWDATA25 endpoint, one ordinary
// combinational consumer, and the retained L48 PIN_18 observation surface.
// This asks only whether the exact DIN69 route admitted by N5.8A conducts.
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

  // INIT=AAAA is identity on I0. Keep the consumer at the retained PIN_18
  // output-route source so candidate and control have the same downstream
  // placement and observation path.
  (* keep, BEL="X14Y9_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    hwdata25_identity(
      .CLK(),
      .I({3'bxxx, hwdata25}),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
