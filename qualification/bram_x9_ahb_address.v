// SRAM-safe structural comparison for the native vendor x9 positive control.
// The External-AHB aligned word address directly selects a 1024 x 9 ROM;
// observing q[2:0] should produce eight values across an address sweep.
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
      mem[i] = i[8:0];

  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  // The vendor x9 control uses two route-through slices for the first two
  // readback lanes.  Preserve those identity buffers explicitly so the open
  // graph can model their separate BRAM->LUT and LUT->MCU arcs.
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h0_buffer(.CLK(clk), .I({3'b000, q[0]}), .F(h0), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h1_buffer(.CLK(clk), .I({3'b000, q[1]}), .F(h1), .Q());
  assign h2 = q[2];
endmodule
