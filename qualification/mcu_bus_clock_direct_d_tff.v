// Minimal vendor-topology bus-clock TFF for direct-D feedback qualification.
// Q is the feedback source; the combinational next-state F is the MCU-visible
// observation branch. This lets one slice present Q on OMUX[3z+1] and F on
// OMUX[3z+0], matching the characterized X1Y4 slice2 topology.
module top;
  wire bus_clock;
  wire toggle;
  wire observed;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X14Y11_SLICE7", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00ff), .FF_USED(1'b1))
    tff(.CLK(bus_clock), .I({toggle, 3'b000}), .F(observed), .Q(toggle));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
