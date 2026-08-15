// Candidate third top-edge output pad: PIN_15, pad tile (19,13) slot z1.
//
// Same two-stage ring as pad_only_pin16.v / pad_only_pin18.v, for the same
// reason: each stage's D comes from the other, so there is no self-feedback to
// fold and the pair supplies the interior flip-flop-to-flip-flop path the
// frequency check needs.
//
// PIN_15 was chosen because the production graph admits exactly ONE feeder into
// its slot, RMUX16 -- so the router cannot silently reach the pad through an
// unmeasured feeder. That is precisely how the first production PIN_16 build
// failed: it reached the IOMUX terminal via RMUX24, config-accepted, and did not
// drive.
module top (input clk, output o_pin15);
  reg a = 1'b0;
  reg b = 1'b0;
  always @(posedge clk) begin
    a <= ~b;
    b <= a;
  end
  assign o_pin15 = a;
endmodule
