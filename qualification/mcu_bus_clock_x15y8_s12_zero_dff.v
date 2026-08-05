// Complementary half of the X15Y8 slice12 ordinary-register discriminator.
// With MCU_RESETN released high, the LUT produces zero. Paired with the
// pass-high image, a low Q proves the site captures both values through the
// ordinary F-to-Q path; no direct-D self-feedback selector participates.
module top;
  wire bus_clock;
  wire resetn;
  wire captured;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep *) MCU_RESETN mcu_reset(.RESETN(resetn));

  (* keep, BEL="X15Y8_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5555), .FF_USED(1'b1))
    candidate_dff(.CLK(bus_clock), .I({3'b000, resetn}),
                  .F(), .Q(captured));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(captured));
endmodule
