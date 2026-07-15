// Dedicated-carry qualification design.  Reading all four (cnt[7],cnt[0])
// combinations proves propagation through eight consecutive Cin/Cout stages.
module top(input clk);
  wire h0, h1;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));

  reg [7:0] cnt;
  always @(posedge clk)
    cnt <= cnt + 1'b1;

  assign h0 = cnt[0];
  assign h1 = cnt[7];
endmodule
