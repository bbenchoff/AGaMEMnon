// Open-flow AHB-slave -> PIN_18: the MCU writes 0x60000000 over mem_ahb; the fabric captures write-data
// bit0 into datareg (placed at the proven pad-route source (14,9)) and drives it onto PIN_18. The MCU
// firmware writes 0/1 at ~1 Hz -> PIN_18 blinks visibly. hwdata0/hwrite/htrans1 enter at col 13/14
// (adjacent to (14,9)); wr_ph gates the data-phase capture. Clocked by the open fabric CLKGEN (100 MHz).
module top (input clk, output o);
  wire hwdata0, hwrite, htrans1;
  (* keep *) MCU_DIN mcu_hwdata0 (.DIN(hwdata0));
  (* keep *) MCU_DIN mcu_hwrite  (.DIN(hwrite));
  (* keep *) MCU_DIN mcu_htrans1 (.DIN(htrans1));
  reg wr_ph = 1'b0, datareg = 1'b0;
  always @(posedge clk) begin
    wr_ph   <= hwrite & htrans1;      // address phase: a write transfer is starting
    if (wr_ph) datareg <= hwdata0;    // data phase: latch write-data bit 0
  end
  assign o = datareg;                 // -> OPAD (18,13)z0 = PIN_18
endmodule
