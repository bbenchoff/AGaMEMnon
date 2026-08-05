// X15Y8 slice12 direct-D candidate: I1/IMUX49, template [18,21].
module top;
  wire bus_clock, toggle, observed;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep, BEL="X15Y8_SLICE12", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h3333), .FF_USED(1'b1))
    tff(.CLK(bus_clock), .I({2'b00, toggle, 1'b0}), .F(observed), .Q(toggle));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
