// x9 upper-output discriminator: DataOutA[12] should drive HRDATA[3] high.
module top(input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  wire [9:0] addr = {7'b0, ahb_word};

  wire h3;
  (* keep *) MCU_DOUT mcu_h3(.DOUT(h3));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = 9'h1ff;
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  (* keep, BEL="X14Y4_SLICE0", AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    data3_buffer(.CLK(clk), .I({q[3], 3'b000}), .F(h3), .Q());
endmodule
