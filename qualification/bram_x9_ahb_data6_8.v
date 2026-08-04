// Pure-open x9 breadth oracle for the three remaining logical data lanes.
// Project live aligned word-address bits 0..2 onto x9 data bits 6..8 so each
// lane has an independent 256-read signature.  Explicit route-through slices
// keep BRAM-output and MCU-exit arcs separately visible to the strict graph.
module top(input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  wire [9:0] addr = {7'b0, ahb_word};

  wire h0, h1, h2;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h1));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(h2));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      // Full-width permutation prevents synthesis from compacting the three
      // observed bits onto low physical DataOutA terminals.
      mem[i] = {i[2:0], i[8:3]};

  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  (* keep, AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h0_buffer(.CLK(clk), .I({3'b000, q[6]}), .F(h0), .Q());
  (* keep, AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h1_buffer(.CLK(clk), .I({3'b000, q[7]}), .F(h1), .Q());
  assign h2 = q[8];
endmodule
