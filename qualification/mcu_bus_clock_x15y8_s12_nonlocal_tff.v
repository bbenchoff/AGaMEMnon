// Two-slice TFF using the silicon-live X15Y8 OMUX37->IMUX16 branch.
// Slice4 computes ~Q; its routable F returns through the normal mesh to the
// ordinary I3/F-to-Q register path at slice12.  This does not claim a direct
// same-slice feedback branch.
module top;
  wire bus_clock, registered_q, next_state;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X15Y8_SLICE12", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hff00), .FF_USED(1'b1))
    state(.CLK(bus_clock), .I({next_state, 3'b000}),
          .F(), .Q(registered_q));
  (* keep, BEL="X15Y8_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5555), .FF_USED(1'b0))
    invert(.CLK(bus_clock), .I({3'b000, registered_q}),
           .F(next_state), .Q());
  (* keep *) MCU_DOUT mcu_h0(.DOUT(next_state));
endmodule
