// Explicit four-site direct-D counter for site-pool and divider qualification.
module top;
  wire bus_clock;
  wire q0, q1, q2, q3;
  wire f0, f1, f2, f3;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));

  (* keep, BEL="X14Y11_SLICE4", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00ff), .FF_USED(1'b1))
    bit0(.CLK(bus_clock), .I({q0, 3'b000}), .F(f0), .Q(q0));

  (* keep, BEL="X14Y11_SLICE5", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'haa55), .FF_USED(1'b1))
    bit1(.CLK(bus_clock), .I({q1, 2'b00, f0}), .F(f1), .Q(q1));

  (* keep, BEL="X14Y11_SLICE6", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hee11), .FF_USED(1'b1))
    bit2(.CLK(bus_clock), .I({q2, 1'b0, f1, f0}), .F(f2), .Q(q2));

  (* keep, BEL="X14Y11_SLICE7", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hfe01), .FF_USED(1'b1))
    bit3(.CLK(bus_clock), .I({q3, f2, f1, f0}), .F(f3), .Q(q3));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(f0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(f1));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(f2));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(f3));
endmodule
