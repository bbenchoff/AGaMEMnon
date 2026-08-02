// Differential silicon control for local_int[0]: identical exact corridor,
// but the retained source LUT drives low instead of high.
module top;
  wire local_irq0;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) local_irq0_constant(
    .I(4'b0000), .Q(local_irq0));
  (* keep *) MCU_LOCAL_INT0 mcu_local_int0(.DOUT(local_irq0));
endmodule
