// Dynamic ordinary-register discriminator for X15Y8 slice12.
// Qualified GPIO4.1 ingress drives the ordinary F-to-Q path. Firmware holds
// the input high/low/high across bus-clock intervals and observes Q through
// MCU_DOUT. No direct-D self-feedback selector participates.
module top;
  wire bus_clock;
  wire gpio_data;
  wire captured;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  // GPIO4.1 is the already-qualified MCU0 fabric ingress used by the retained
  // reset firmware. Pin it so the firmware/oracle binding cannot drift to a
  // different MCU DIN lane during placement.
  (* keep, BEL="X10Y5_MCU0" *) MCU mcu_data(.DIN(gpio_data));

  (* keep, BEL="X15Y8_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hff00), .FF_USED(1'b1))
    candidate_dff(.CLK(bus_clock), .I({gpio_data, 3'b000}),
                  .F(), .Q(captured));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(captured));
endmodule
