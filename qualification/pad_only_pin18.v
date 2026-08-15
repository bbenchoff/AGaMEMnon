// Independence control: PIN_18 alone, from the same production flow.
//
// A two-stage ring rather than a toggle plus a dangling register. A dangling
// extra stage is optimised away, and driving the pad from the SECOND stage of a
// self-feedback toggle left the ~q0 feedback routed across tiles -- (18,12) to
// (14,11) to (14,12) and back -- instead of through the slice's own pinC path,
// and the pad read static. Here each stage's D comes from the other, so the
// interior flip-flop-to-flip-flop path the frequency check needs is the
// oscillator itself and neither stage needs self-feedback.
//
// The unused pad is OMITTED, not tied low: a tied-low output still creates an
// IOB whose constant must be routed to that pad, and that route emits CFG_RMUX
// bits at the tile that is the other pad's config tile.
module top (input clk, output o_pin18);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin18 = a;
endmodule
