// Scale test: 4-bit counter, ALL cells packed dense on ONE tile by pin_densepack (even slots).
// Reads d[3:0] -> h0..h3. If distinct is large (up to 16) on silicon, a multi-cell connected structure
// (carry chain + FFs) packs dense on one tile and computes -- the dense-packing scale proof.
module top(input clk);
  wire h0, h1, h2, h3;
  (* keep *) MCU_DOUT h0c(.DOUT(h0));
  (* keep *) MCU_DOUT h1c(.DOUT(h1));
  (* keep *) MCU_DOUT h2c(.DOUT(h2));
  (* keep *) MCU_DOUT h3c(.DOUT(h3));
  reg [3:0] d = 4'b0; always @(posedge clk) d <= d + 4'b1;
  assign h0 = d[0]; assign h1 = d[1]; assign h2 = d[2]; assign h3 = d[3];
endmodule
