// Return-half discriminator with the slice4 truth table inverted.
module top;
  wire bus_clock, gpio_data, next_state, captured;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X10Y5_MCU0" *) MCU mcu_data(.DIN(gpio_data));
  (* keep, BEL="X15Y8_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5555), .FF_USED(1'b0))
    source(.CLK(bus_clock), .I({3'b000, gpio_data}), .F(next_state), .Q());
  (* keep, BEL="X15Y8_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hff00), .FF_USED(1'b1))
    capture(.CLK(bus_clock), .I({next_state, 3'b000}), .F(), .Q(captured));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(captured));
endmodule
