// SRAM-only x9 terminal-identity permutations.
//
// Vendor SDK RTL confirms that the native hard-block port is named AddressA,
// while the physical IMUX09/08/07 -> AddressA[3:5] identity remains the open
// question.  The identity mapping was already silicon-negative.  These five
// wrappers cover every non-identity permutation without changing BRAM mode,
// initialization, clocking, readback, or the qualified HADDR source lanes.
module x9_address_permutation #(parameter P0 = 0, P1 = 1, P2 = 2) (input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  wire [2:0] permuted_word = {ahb_word[P2], ahb_word[P1], ahb_word[P0]};
  wire [9:0] addr = {7'b0, permuted_word};

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

  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h0_buffer(.CLK(clk), .I({3'b000, q[0]}), .F(h0), .Q());
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    x9_h1_buffer(.CLK(clk), .I({3'b000, q[1]}), .F(h1), .Q());
  assign h2 = q[2];
endmodule

module top_swap34(input clk);
  x9_address_permutation #(.P0(1), .P1(0), .P2(2)) dut(.clk(clk));
endmodule

module top_swap35(input clk);
  x9_address_permutation #(.P0(2), .P1(1), .P2(0)) dut(.clk(clk));
endmodule

module top_swap45(input clk);
  x9_address_permutation #(.P0(0), .P1(2), .P2(1)) dut(.clk(clk));
endmodule

module top_cycle345(input clk);
  x9_address_permutation #(.P0(1), .P1(2), .P2(0)) dut(.clk(clk));
endmodule

module top_cycle354(input clk);
  x9_address_permutation #(.P0(2), .P1(0), .P2(1)) dut(.clk(clk));
endmodule
