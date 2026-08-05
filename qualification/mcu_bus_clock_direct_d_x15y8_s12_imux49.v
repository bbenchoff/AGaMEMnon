// Experimental exact-site direct-D TFF for X15Y8 slice12.
//
// The retained route corpus observes the same-slice feedback wire OMUX37
// entering this slice through I1/IMUX49 with CFG_IMUX12[6,9].  This differs
// from the rejected coordinate substitution, which used I3/IMUX51.  The
// environment-gated site remains outside the release pool until silicon
// observes both states.
module top;
  wire bus_clock;
  wire toggle;
  wire observed;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X15Y8_SLICE12", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h3333), .FF_USED(1'b1))
    tff(.CLK(bus_clock), .I({2'b00, toggle, 1'b0}),
        .F(observed), .Q(toggle));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
