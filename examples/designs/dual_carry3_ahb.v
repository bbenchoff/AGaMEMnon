// Same-tile multi-chain dedicated-carry qualification. Two independent
// three-bit adders require two physical carry seeds and two disjoint Cin/Cout
// chains. Reading each counter's LSB/MSB proves both chains advance.
module top(input clk);
  wire h0, h1, h2, h3;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(h2));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(h3));

  reg [2:0] count_by_1;
  reg [2:0] count_by_3;
  always @(posedge clk) begin
    count_by_1 <= count_by_1 + 3'd1;
    count_by_3 <= count_by_3 + 3'd3;
  end

  assign h0 = count_by_1[0];
  assign h1 = count_by_1[2];
  assign h2 = count_by_3[0];
  assign h3 = count_by_3[2];
endmodule
