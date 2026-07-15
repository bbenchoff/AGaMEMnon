// Archived inconclusive physical-input/AHB probe. Its AHB value stayed high
// because the selected MCU exit was not independently qualified. The direct
// PIN15-to-PIN16 control in input_pin15_to_pin16.v is the promoted input proof.
module top(input a);
  wire a_buf;
  (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) input_buffer(
      .I({3'b000, a}), .Q(a_buf));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(a_buf));
endmodule
