// Static hardware oracle for left-edge outputs.  The inversion forces a LUT
// between the independently qualified top-edge input and the selected output,
// so driving the input low/high must produce unambiguous high/low pad states.
module top(input i, output o);
  assign o = ~i;
endmodule
