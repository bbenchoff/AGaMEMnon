// Two independent top-edge ring-pad outputs, PIN_18 and PIN_16, from one image.
//
// Ordinary Verilog with no lab hooks. The pads deliberately share a tile --
// PIN_16's config tile (18,13) is PIN_18's pad tile -- because that is the
// composition most likely to interfere.
//
// Each pad is driven by its own two-stage ring rather than a self-feedback
// toggle. Two reasons, both measured: a ring has no self-feedback for qin_pack
// to fold, and it supplies the interior flip-flop-to-flip-flop path the CLI's
// frequency check needs (with every flip-flop going straight to a pad, nextpnr
// reports no Fmax and the build fails). The toggle-plus-pipeline form also left
// the router unable to reach the pinned pad approach.
module top (input clk, output o_pin18, output o_pin16);
  reg a0 = 1'b0;
  reg b0 = 1'b0;
  always @(posedge clk) begin
    a0 <= ~b0;
    b0 <= a0;
  end
  assign o_pin18 = a0;

  reg a1 = 1'b0;
  reg b1 = 1'b0;
  always @(posedge clk) begin
    a1 <= ~b1;
    b1 <= a1;
  end
  assign o_pin16 = a1;
endmodule
