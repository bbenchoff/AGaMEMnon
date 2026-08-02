// Safe-default smoke: one retained constant-low source fans out through all
// four recovered local_int hard-boundary corridors.
module top;
  wire local_irq_low;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) local_irq_constant_low(
    .I(4'b0000), .Q(local_irq_low));
  (* keep *) MCU_LOCAL_INT0 mcu_local_int0(.DOUT(local_irq_low));
  (* keep *) MCU_LOCAL_INT1 mcu_local_int1(.DOUT(local_irq_low));
  (* keep *) MCU_LOCAL_INT2 mcu_local_int2(.DOUT(local_irq_low));
  (* keep *) MCU_LOCAL_INT3 mcu_local_int3(.DOUT(local_irq_low));
endmodule
