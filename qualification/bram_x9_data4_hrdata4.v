// Isolated x9 logical data-bit4 corridor from the working vendor control.
//
// Keep address ingress inside the silicon-qualified HADDR[2:5] subset and
// encode aligned word-address bit 3 (HADDR5) into data bit 4.  This distinguishes the BRAM data lane and
// its direct egress without depending on an unqualified high-address input.
module top(input clk);
  wire [3:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(ahb_word[3]));
  wire [9:0] addr = {6'b0, ahb_word};

  wire h4;
  (* keep *) MCU_DOUT mcu_h4(.DOUT(h4));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = {i[8:5], i[3], i[4], i[2:0]};
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  assign h4 = q[4];
endmodule
