// Hardware-free strict smoke for one additional MCU GPIO boundary unit.
// This reproduces the vendor GPIO5 data/OE XOR route; it is not silicon-qualified.
module top;
  (* keep *) wire gpio5_data1, gpio5_oe1, gpio5_input2;

  (* keep *) MCU_GPIO5_OUT_DATA1 data_source(.DIN(gpio5_data1));
  (* keep *) MCU_GPIO5_OUT_EN1 enable_source(.DIN(gpio5_oe1));
  // Plain vendor alta_slice instances set CarryEnb=1. This disables the
  // carry-chain takeover of the D input; the exact open bit is opt-in here.
  (* keep, BEL="X9Y4_SLICE0", AGRV2K_CARRY_CRL=1 *)
  LUT #(.K(4), .INIT(16'h0ff0)) gpio5_xor(
    .I({gpio5_data1, gpio5_oe1, 2'b00}), .Q(gpio5_input2));
  (* keep *) MCU_GPIO5_IN2 observation_sink(.DOUT(gpio5_input2));
endmodule
