// Inter-tile dedicated-carry qualification design.  The physical carry packer
// places the seed and bits 0..14 in X20Y12, then bit 15 in X20Y11.  Observing all
// four (cnt[15], cnt[0]) states proves that the horizontal COUT15 -> CIN0 seam
// is live; a same-tile-only chain cannot produce a varying cnt[15].
module top(input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));

  reg [15:0] cnt;
  always @(posedge clk)
    cnt <= cnt + 1'b1;

  assign h0 = cnt[0];
  assign h1 = cnt[15];
endmodule
