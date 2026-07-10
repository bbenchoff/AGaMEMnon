// Multi-bit sequential counter, read over the MCU AHB bus (0x60000000) — the design proven to COMPUTE on
// silicon through the agrv2k nextpnr uarch (2026-07-09). A 4-bit counter whose bit 0 and bit 3 are read
// back: bit 3 only cycles when the carry propagates through all 4 bits, so seeing all four (bit3,bit0)
// combinations over AHB proves real multi-bit sequential logic (not a stuck/toggle-only output).
//
// Flow (see examples/uarch_sequential.md): yosys (LUT logic, Qin self-feedback) -> fanout_split ->
// nextpnr --uarch agrv2k on the CONDUCTION-GATED device with the conduction-aware placer -> open bitgen.
module top (input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0 (.DOUT(h0));   // -> hrdata[0]
  (* keep *) MCU_DOUT mcu_h1 (.DOUT(h1));   // -> hrdata[1]
  reg [3:0] cnt;
  always @(posedge clk) cnt <= cnt + 1'b1;
  assign h0 = cnt[0];   // toggles every cycle
  assign h1 = cnt[3];   // toggles only via the full 4-bit carry
endmodule
