// Bounded, default-off synchronous-clear silicon candidate.
//
// With AGAMEMNON_NATIVE_SYNC_CLEAR_X14Y12_S0 enabled, the frontend preserves
// exactly one positive-edge, active-high synchronous clear-to-zero register.
// The uarch hard-binds it to X14Y12_SLICE0 and exposes only the desk-decoded
// RMUX90 -> CtrlMUX03 -> TileSyncMUX00 ingress.  With the option disabled the
// same RTL takes the established LUT-on-D lowering, providing the control arm
// for a later SRAM-only silicon A/B.  Emission is not a silicon claim.
module top;
  wire hclk;
  wire haddr2;
  wire haddr4;
  wire q;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(haddr4));

  reg state;
  always @(posedge hclk)
    if (haddr2)
      state <= 1'b0;
    else
      state <= haddr4;
  assign q = state;

  // q is the behavioral witness; haddr2 is echoed beside it so the MCU-side
  // harness can reject a bad control stimulus instead of trusting q alone.
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(1'b1));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(q));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(haddr2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(1'b0));
endmodule
