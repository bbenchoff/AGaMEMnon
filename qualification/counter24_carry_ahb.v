// Archived vendor-seam reconstruction probe. A laboratory backend placed one
// seed plus 24 arithmetic stages across X10Y4 and X10Y3. The open image was
// static, so the release packer now rejects this design under --hard-carry.
module top(input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));

  reg [23:0] cnt;
  always @(posedge clk)
    cnt <= cnt + 1'b1;

  assign h0 = cnt[0];
  assign h1 = cnt[23];
endmodule
