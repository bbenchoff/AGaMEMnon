// Causal HRESP-high control. This is not a legal public endpoint because it
// asserts ERROR while idle; it exists only to distinguish hard-port response
// visibility from address/transfer decode behavior.
module top;
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(1'b1));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(1'b1));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(1'b1));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(1'b1));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(1'b1));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(1'b1));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(1'b0));
endmodule
