// N5.8B alternate-terminal discriminator: retain the accepted typed HWDATA25
// endpoint and fixed LUT site, but consume it on ordinary input I1 instead of
// the previously silicon-qualified I0 terminal.
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

  // INIT=CCCC is identity on I1. The accepted S02 composition used I0 and
  // INIT=AAAA at this same site; the output route remains independently fixed.
  (* keep, BEL="X14Y9_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCCCC), .FF_USED(1'b0))
    hwdata25_i1_identity(
      .CLK(),
      .I({2'bxx, hwdata25, 1'bx}),
      .F(observed_lut),
      .Q()
    );

  assign observed = observed_lut;
endmodule
