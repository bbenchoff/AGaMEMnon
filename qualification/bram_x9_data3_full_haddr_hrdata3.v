// x9 breadth oracle: retain all ten logical word-address inputs while
// observing logical data bit 3 through the vendor q3 readback corridor.
module top(input clk);
  wire [8:0] word_addr_low;
  wire haddr11_raw, haddr11_buffered;
  (* keep *) MCU_DIN mcu_haddr2 (.DIN(word_addr_low[0]));
  (* keep *) MCU_DIN mcu_haddr3 (.DIN(word_addr_low[1]));
  (* keep *) MCU_DIN mcu_haddr4 (.DIN(word_addr_low[2]));
  (* keep *) MCU_DIN mcu_haddr5 (.DIN(word_addr_low[3]));
  (* keep *) MCU_DIN mcu_haddr6 (.DIN(word_addr_low[4]));
  (* keep *) MCU_DIN mcu_haddr7 (.DIN(word_addr_low[5]));
  (* keep *) MCU_DIN mcu_haddr8 (.DIN(word_addr_low[6]));
  (* keep *) MCU_DIN mcu_haddr9 (.DIN(word_addr_low[7]));
  (* keep *) MCU_DIN mcu_haddr10(.DIN(word_addr_low[8]));
  (* keep *) MCU_DIN mcu_haddr11(.DIN(haddr11_raw));
  (* keep, BEL="X14Y7_SLICE3", AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    haddr11_buffer(.CLK(clk), .I({haddr11_raw, 3'b000}),
                   .F(haddr11_buffered), .Q());
  wire [9:0] word_addr = {haddr11_buffered, word_addr_low};

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
