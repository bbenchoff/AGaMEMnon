// Isolated x9 logical data-bit3 corridor recovered from the retained vendor
// route: DataOutA[12]/BufMUX11 -> X14Y4 slice12 I3 -> HRDATA12.
module top(input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  wire [9:0] addr = {7'b0, ahb_word};

  wire h12;
  (* keep *) MCU_DOUT mcu_h12(.DOUT(h12));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = i[8:0];
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  (* keep, BEL="X14Y4_SLICE12", AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    data3_buffer(.CLK(clk), .I({q[3], 3'b000}), .F(h12), .Q());
endmodule
