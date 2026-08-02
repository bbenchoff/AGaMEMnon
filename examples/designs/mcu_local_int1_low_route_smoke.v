// Differential silicon control for local_int[1].
module top;
  wire local_irq1;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) local_irq1_constant(
    .I(4'b0000), .Q(local_irq1));
  (* keep *) MCU_LOCAL_INT1 mcu_local_int1(.DOUT(local_irq1));
endmodule
