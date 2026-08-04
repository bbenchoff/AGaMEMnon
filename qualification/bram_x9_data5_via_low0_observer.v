// Alternate-observer discriminator for the first fail-closed x9 data lane.
// Physical DataOutA14/BufMUX13 is routed through the already-qualified
// X14Y4 slice5 identity footprint and observed on MCU HRDATA0.  The INIT
// permutation projects aligned word-address bit3 onto logical data bit5.
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
      mem[i] = {i[8:6], i[3], i[4], i[5], i[2:0]};
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[word_addr];

  // Deliberately unannotated while RMUX72->IMUX20 is an experimental final
  // edge. The workbench applies only the qualified non-selector slice bytes;
  // release bitgen continues to fail closed for this route.
  (* keep, BEL="X14Y4_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    data5_observer(.CLK(clk), .I({3'b000, q[5]}), .F(h0), .Q());
endmodule
