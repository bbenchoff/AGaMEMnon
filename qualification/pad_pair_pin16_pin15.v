// Two top-edge output pads from one image: PIN_16 and PIN_15.
//
// Deliberately the most interference-prone pairing available. Both pads live on
// the SAME pad tile (19,13) in adjacent slots -- PIN_16 is z0, PIN_15 is z1 --
// so they share one config tile (18,13) and their CFG_IOMUX slot bits sit in
// neighbouring blocks of the same banks. If park/unpark or source-select were
// approximate rather than exact, this is the composition that would show it.
//
// PIN_18 is NOT the partner here on purpose: its pad-feed codeword writes eight
// bits at (18,13), which is PIN_15's config tile, and one of those bits is one
// of PIN_15's own two codeword bits.
//
// Each output is an independent two-stage ring, so neither pad is a constant and
// both provide the interior flip-flop-to-flip-flop path the frequency check
// wants.
module top (input clk, output o_pin16, output o_pin15);
  reg a = 1'b0;
  reg b = 1'b0;
  reg c = 1'b0;
  reg d = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
    c <= ~d;
    d <= c;
  end
  assign o_pin16 = a;
  assign o_pin15 = c;
endmodule
