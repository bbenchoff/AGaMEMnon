// Open-flow 2-bit MCU<->fabric loopback: TWO independent GPIO bits, each MCU-out -> fabric LUT
// inverter -> MCU-in, crossing the MCU edge on its OWN harvested wires.
//   bit0: din0(GPIO4_1) -> RMUX93 entry -> LUT -> RMUX19 exit -> BBMUXS02 -> dout0(GPIO4_2)
//   bit1: din1(GPIO4_3) -> RMUX17 entry -> LUT -> RMUX02 exit -> BBMUXS04 -> dout1(GPIO4_4)
// Each MCU cell maps 1:1 onto an MCU bel (arch.py adds one per bit). Two LUT4 inverters.
module top;
  wire din0, dout0, din1, dout1;
  (* keep *) MCU mcu0 (.DIN(din0), .DOUT(dout0));
  (* keep *) MCU mcu1 (.DIN(din1), .DOUT(dout1));
  assign dout0 = ~din0;
  assign dout1 = ~din1;
endmodule
