module top(input a, input b, input c, input d, output o);
  assign o = (a & b) | (c ^ d);
endmodule
