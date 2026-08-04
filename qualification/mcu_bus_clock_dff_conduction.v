// SRAM-only isolation oracle for MCU_BUS_CLOCK delivery.
//
// The forced slice captures the released MCU reset level.  Its initialized Q
// is low and becomes high only after a delivered bus-clock edge.  There is no
// Q-to-D feedback path, so this separates clock conduction from the direct-D
// TFF lowering under qualification.
module top;
  wire bus_clock;
  wire resetn;
  wire captured;
  wire observed;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep *) MCU_RESETN mcu_reset(.RESETN(resetn));
  // A separate combinational slice buffers Q to the established MCU_DOUT
  // sink; it does not feed the tested FF's D.
  (* keep, BEL="X1Y4_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b1))
    probe(.CLK(bus_clock), .I({3'b000, resetn}), .F(), .Q(captured));
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b0))
    observe_buffer(.CLK(bus_clock), .I({3'b000, captured}), .F(observed), .Q());
  (* keep *) MCU_DOUT mcu_observe(.DOUT(observed));

endmodule
