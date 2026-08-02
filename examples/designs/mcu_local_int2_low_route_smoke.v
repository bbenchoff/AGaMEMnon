// Differential silicon control for local_int[2].
module top;
  wire local_irq2;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) local_irq2_constant(
    .I(4'b0000), .Q(local_irq2));
  (* keep *) MCU_LOCAL_INT2 mcu_local_int2(.DOUT(local_irq2));
endmodule
