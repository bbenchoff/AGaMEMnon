// Archived inter-tile carry seam probe. It was built with a laboratory packer
// that placed the seed at slice 14, bit 0 at slice 15, and bit 1 at the tile
// below slice 0. The sweep produced isolated negative evidence, so the release
// packer no longer exposes the placement overrides or inter-tile seam.
module top(input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));

  reg [1:0] cnt;
  always @(posedge clk)
    cnt <= cnt + 1'b1;

  assign h0 = cnt[0];
  assign h1 = cnt[1];
endmodule
