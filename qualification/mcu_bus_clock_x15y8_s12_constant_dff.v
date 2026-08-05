// Minimal clock/register discriminator for X15Y8 slice12.
// The LUT passes the released MCU reset level and its own registered Q is
// observed. A high Q requires the candidate site to capture that level; no
// direct-D self-feedback selector participates. This establishes a working
// register/Q path, not hard-reset semantics or exclusive BUSCLK attribution.
module top;
  wire bus_clock;
  wire resetn;
  wire captured;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep *) MCU_RESETN mcu_reset(.RESETN(resetn));

  (* keep, BEL="X15Y8_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b1))
    candidate_dff(.CLK(bus_clock), .I({3'b000, resetn}),
                  .F(), .Q(captured));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(captured));
endmodule
