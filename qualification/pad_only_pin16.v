// Independence control: PIN_16 alone, from the same production flow.
//
// A two-stage ring, matching pad_only_pin18.v. The toggle-plus-pipeline form
// leaves the ~q feedback to be routed, and with the qualified pad composition
// pinned the router could not then reach the single allowed approach: the build
// failed with "Failed to route arc 0.0 of net q1_d". Each stage's D coming from
// the other removes the self-feedback entirely and supplies the interior
// flip-flop-to-flip-flop path the frequency check needs.
module top (input clk, output o_pin16);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin16 = a;
endmodule
