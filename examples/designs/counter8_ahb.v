// 8-bit sequential counter read over the MCU AHB bus (0x60000000). Bits 0 and 7 are read back: bit 7
// only cycles after the carry propagates through all 8 bits, so seeing every (bit7,bit0) combination
// over AHB proves an 8-bit sequential datapath (a wider stress of the agrv2k uarch than counter_ahb.v).
module top (input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0 (.DOUT(h0));   // -> hrdata[0]
  (* keep *) MCU_DOUT mcu_h1 (.DOUT(h1));   // -> hrdata[1]
  reg [7:0] cnt;
  always @(posedge clk) cnt <= cnt + 1'b1;
  assign h0 = cnt[0];   // toggles every cycle
  assign h1 = cnt[7];   // toggles only via the full 8-bit carry
endmodule
