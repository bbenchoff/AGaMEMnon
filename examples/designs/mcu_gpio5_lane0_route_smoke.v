// L48-only differential hard-boundary oracle for GPIO5 lane 0.
module top;
  (* keep *) wire gpio5_data0, gpio5_oe0, gpio5_input2;

  (* keep *) MCU_GPIO5_OUT_DATA0 data_source(.DIN(gpio5_data0));
  (* keep *) MCU_GPIO5_OUT_EN0 enable_source(.DIN(gpio5_oe0));
  (* keep, BEL="X9Y4_SLICE3", AGRV2K_CARRY_CRL=1, AGRV2K_MCU_PINPACKED=1 *)
  LUT #(.K(4), .INIT(16'h0ff0)) gpio5_xor(
    .I({gpio5_data0, gpio5_oe0, 2'b00}), .Q(gpio5_input2));
  (* keep *) MCU_GPIO5_IN2 observation_sink(.DOUT(gpio5_input2));
endmodule
