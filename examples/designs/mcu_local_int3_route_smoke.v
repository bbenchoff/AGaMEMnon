// Hardware-free strict-routing smoke for the recovered local_int[3] corridor.
module top;
  wire local_irq3;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'hffff)) local_irq3_constant(
    .I(4'b0000), .Q(local_irq3));
  (* keep *) MCU_LOCAL_INT3 mcu_local_int3(.DOUT(local_irq3));
endmodule
