// Dedicated silicon discriminator for the qualified HSIZE[1] logic corridor.
//
// A word access has HSIZE[1]=1; byte and halfword accesses have HSIZE[1]=0.
// The ingress is deliberately isolated from BRAM and register-bank behavior,
// so its silicon result qualifies only this hard-port-to-LUT route. It is not
// a byte-enable or wider register-bank claim. The generic relative selector
// chose CFG_RMUX5 {43,49} for InputMUX05 -> RMUX34 and read constant one;
// the vendor oracle measured {42,48}, which passes 256 fixed-address reads for
// each transfer size. That exact codeword now lives in
// chipdb/mcu_hsize1_logic_pip_cfg.csv and fails closed if it disappears.
(* top *)
module top;
  wire hsize1, observed;

  (* keep *) MCU_AHB_HSIZE1 mcu_hsize1(.DIN(hsize1));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));

  // Vendor XOR oracle routes HSIZE1 to X14Y12_SLICE3/I2 through
  // BufMUX04 -> InputMUX05 -> RMUX34 -> IMUX14.
  (* keep, BEL = "X14Y12_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hF0F0), .FF_USED(1'b0))
    hsize1_identity(.CLK(1'b0), .I({1'b0, hsize1, 2'b00}), .F(observed), .Q());
endmodule
