// Differential silicon control for local_int[3].
module top;
  wire local_irq3;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) local_irq3_constant(
    .I(4'b0000), .Q(local_irq3));
  (* keep *) MCU_LOCAL_INT3 mcu_local_int3(.DOUT(local_irq3));
endmodule
