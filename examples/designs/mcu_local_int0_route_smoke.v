// Hardware-free strict-routing smoke for the recovered local_int[0] corridor.
// Behavioral interrupt qualification requires the SRAM MCU harness.
module top;
  wire local_irq0;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'hffff)) local_irq0_constant(
    .I(4'b0000), .Q(local_irq0));
  (* keep *) MCU_LOCAL_INT0 mcu_local_int0(.DOUT(local_irq0));
endmodule
