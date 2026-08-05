// Isolated X14Y11 slice5/I3 conduction discriminator.
module top;
  wire haddr2;
  wire hrdata2;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(hrdata2));
  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b0))
    observer(.I({haddr2, 3'b000}), .F(hrdata2), .Q());
endmodule
