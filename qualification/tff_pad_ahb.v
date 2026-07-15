// Distinguish source-state activity from physical-pad conduction.  The same
// flip-flop drives both the constrained output pad and MCU AHB read lane 0.
module top(input clk, output o);
  wire h0;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  reg q;
  always @(posedge clk)
    q <= ~q;
  assign o = q;
  assign h0 = q;
endmodule
