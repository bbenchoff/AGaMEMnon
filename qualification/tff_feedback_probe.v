// Isolated physical feedback probe.  The first FF toggles through its local
// Qin feedback resource; the second FF transports that state to the qualified
// PIN_16 output source.  A placement replay map can pin only the first FF to a
// candidate slice without changing the output-pad route.
module top(input clk, output o);
  (* keep *) reg q;
  (* keep *) reg q_out;
  always @(posedge clk) begin
    q <= ~q;
    q_out <= q;
  end
  assign o = q_out;
endmodule
