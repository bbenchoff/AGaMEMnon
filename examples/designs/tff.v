module top(input clk, output o);
  reg q;
  always @(posedge clk) q <= ~q;   // toggle flip-flop: minimal sequential design
  assign o = q;
endmodule
