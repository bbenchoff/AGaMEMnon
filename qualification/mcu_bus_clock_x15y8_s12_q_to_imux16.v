// Q-presentation discriminator: X15Y8 slice12 -> slice4 I0/IMUX16.
module top;
  wire bus_clock, gpio_data, registered_q, observed;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X10Y5_MCU0" *) MCU mcu_data(.DIN(gpio_data));
  (* keep, BEL="X15Y8_SLICE12", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hff00), .FF_USED(1'b1))
    capture(.CLK(bus_clock), .I({gpio_data, 3'b000}), .F(), .Q(registered_q));
  (* keep, BEL="X15Y8_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b0))
    buffer(.CLK(bus_clock), .I({3'b000, registered_q}), .F(observed), .Q());
  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
