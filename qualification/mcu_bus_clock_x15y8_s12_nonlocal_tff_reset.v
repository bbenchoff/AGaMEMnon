// Deterministically resettable two-slice TFF at X15Y8.
// Slice4 computes reset ? 0 : ~Q from Q on I0 and GPIO4.1 reset on I3.
module top;
  wire bus_clock, reset, registered_q, next_state;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X10Y5_MCU0" *) MCU mcu_reset(.DIN(reset));
  (* keep, BEL="X15Y8_SLICE12", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hff00), .FF_USED(1'b1))
    state(.CLK(bus_clock), .I({next_state, 3'b000}),
          .F(), .Q(registered_q));
  (* keep, BEL="X15Y8_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0055), .FF_USED(1'b0))
    feedback(.CLK(bus_clock), .I({reset, 2'b00, registered_q}),
             .F(next_state), .Q());
  (* keep *) MCU_DOUT mcu_h0(.DOUT(next_state));
endmodule
