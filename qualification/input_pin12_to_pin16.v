// Decimal L48 package lead PIN_12 sampled through fabric and observed at the
// already-qualified PIN_16 output.  Inversion makes the external truth table
// unambiguous and keeps the path entirely combinational (no clock hypothesis).
module top(input pin_in, output pin_out);
  assign pin_out = ~pin_in;
endmodule
