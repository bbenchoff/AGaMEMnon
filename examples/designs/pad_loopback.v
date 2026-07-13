// Minimal physical-I/O smoke test: one package input routed combinationally to one package output.
module top(input pin_in, output pin_out);
  assign pin_out = pin_in;
endmodule
