// Pure-open X13Y4 x9 payoff oracle: expose all nine initialized data bits on
// External-AHB HRDATA[8:0] and require 256 complete identity words.
module top(input clk);
  wire [7:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(ahb_word[3]));
  (* keep *) MCU_DIN mcu_haddr6(.DIN(ahb_word[4]));
  (* keep *) MCU_DIN mcu_haddr7(.DIN(ahb_word[5]));
  (* keep *) MCU_DIN mcu_haddr8(.DIN(ahb_word[6]));
  (* keep *) MCU_DIN mcu_haddr9(.DIN(ahb_word[7]));
  wire [9:0] addr = {2'b0, ahb_word};

  wire [8:0] h;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(h[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(h[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(h[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(h[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(h[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(h[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(h[7]));
  (* keep *) MCU_DOUT mcu_h8(.DOUT(h[8]));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = i[8:0];

  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  (* keep, AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h0_buffer(.CLK(clk), .I({3'b000, q[0]}), .F(h[0]), .Q());
  (* keep, AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h1_buffer(.CLK(clk), .I({3'b000, q[1]}), .F(h[1]), .Q());
  // q3 has no qualified direct source-to-HRDATA3 corridor.  Reuse its exact
  // X14Y4 slice0 route-through footprint from the per-lane qualification.
  (* keep, BEL="X14Y4_SLICE0", AGRV2K_ROUTE_THROUGH=1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    x9_h3_buffer(.CLK(clk), .I({q[3], 3'b000}), .F(h[3]), .Q());
  assign h[2] = q[2];
  assign h[8:4] = q[8:4];
endmodule
