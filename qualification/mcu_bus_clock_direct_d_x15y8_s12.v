// Exact-site direct-D TFF broadening candidate derived from the pipelined
// byte-register-bank placement frontier. No support claim exists until both
// states are observed on silicon through the traffic sampler.
module top;
  wire bus_clock;
  wire toggle;
  wire observed;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X15Y8_SLICE12", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00ff), .FF_USED(1'b1))
    tff(.CLK(bus_clock), .I({toggle, 3'b000}), .F(observed), .Q(toggle));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
