// Scale test: 8-bit counter packed dense on ONE tile (8 cells -> even slots 0..14). Taps d[0],d[2],d[5],
// d[7] span the width; if all four vary on silicon the 8-deep carry chain conducts intra-tile end to end.
module top(input clk);
  wire h0, h1, h2, h3;
  (* keep *) MCU_DOUT h0c(.DOUT(h0));
  (* keep *) MCU_DOUT h1c(.DOUT(h1));
  (* keep *) MCU_DOUT h2c(.DOUT(h2));
  (* keep *) MCU_DOUT h3c(.DOUT(h3));
  reg [7:0] d = 8'b0; always @(posedge clk) d <= d + 8'b1;
  assign h0 = d[0]; assign h1 = d[2]; assign h2 = d[5]; assign h3 = d[7];
endmodule
