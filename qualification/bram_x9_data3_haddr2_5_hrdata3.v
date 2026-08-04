// Pure-open x9 data-bit3 oracle over the qualified HADDR[5:2] ingress.
module top(input clk);
  wire [3:0] word_addr_low;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(word_addr_low[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(word_addr_low[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(word_addr_low[2]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(word_addr_low[3]));
  wire [9:0] word_addr = {6'b0, word_addr_low};

  wire h3;
  (* keep *) MCU_DOUT mcu_h3(.DOUT(h3));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = i[8:0];
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[word_addr];

  (* keep, BEL="X14Y4_SLICE0", AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    data3_buffer(.CLK(clk), .I({q[3], 3'b000}), .F(h3), .Q());
endmodule
