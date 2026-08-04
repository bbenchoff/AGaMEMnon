// Isolated HADDR[5]-to-LUT qualification oracle.
module top;
  wire haddr4, haddr5;
  wire value;

  (* keep *) MCU_DIN mcu_haddr4(.DIN(haddr4));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(haddr5));
  (* keep *) LUT #(.K(4), .INIT(16'h6666)) xor_lut
    (.I({2'b00, haddr5, haddr4}), .Q(value));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(value));
endmodule
