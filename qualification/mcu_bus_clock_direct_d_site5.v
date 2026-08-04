// Exact-site direct-D TFF used to broaden the qualified site pool.
module top;
  wire bus_clock;
  wire toggle;
  wire observed;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X14Y11_SLICE5", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00ff), .FF_USED(1'b1))
    tff(.CLK(bus_clock), .I({toggle, 3'b000}), .F(observed), .Q(toggle));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
