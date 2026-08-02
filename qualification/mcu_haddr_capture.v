// SRAM-only isolation probe for the dynamic External-AHB HADDR boundary.
// Capture HADDR[4:2] on the fabric clock and return the registered value on
// HRDATA[2:0].  This separates hard-source/static-enable behavior from BRAM
// addressing, initialization, and control configuration.
module top(input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));

  reg [2:0] captured;
  always @(posedge clk)
    captured <= ahb_word;

  wire h0, h1, h2;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(h2));
  assign h0 = captured[0];
  assign h1 = captured[1];
  assign h2 = captured[2];
endmodule
