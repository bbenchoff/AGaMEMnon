// Positive-control companion for bram_x9_data5_via_low0_observer.v.
// Logical x9 data4 is already silicon-qualified directly; this image tests
// whether the experimental slice5 observer can see that known-live source.
module top(input clk);
  wire [3:0] word_addr_low;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(word_addr_low[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(word_addr_low[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(word_addr_low[2]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(word_addr_low[3]));
  wire [9:0] word_addr = {6'b0, word_addr_low};

  wire h0;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = {i[8:5], i[3], i[4], i[2:0]};
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[word_addr];

  (* keep, BEL="X14Y4_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    data4_observer(.CLK(clk), .I({3'b000, q[4]}), .F(h0), .Q());
endmodule
