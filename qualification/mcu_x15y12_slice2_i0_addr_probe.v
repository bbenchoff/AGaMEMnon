// Isolated X15Y12 slice2/I0 conduction discriminator.
//
// HADDR[2] is the only fabric input.  The forced identity LUT returns it on
// HRDATA[2], so alternating aligned reads at offsets 0 and 4 distinguish a
// live I0 terminal from the constant-high failure seen in the three-bit bank.
module top;
  wire haddr2;
  wire hrdata2;

  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(hrdata2));

  (* keep, BEL = "X15Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    observer(.I({3'b000, haddr2}), .F(hrdata2), .Q());
endmodule
