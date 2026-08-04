// Isolated pure-open x9 logical data8 / physical DataOutA17 breadth oracle.
// A full-width INIT permutation keeps all nine x9 terminals present while
// q[8] carries aligned word-address bit2. Readback is direct so this trial
// does not depend on an unqualified explicit-buffer input footprint.
module top(input clk);
  wire [2:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  wire [9:0] addr = {7'b0, ahb_word};

  wire h0;
  (* keep *) MCU_DOUT mcu_h0(.DOUT(h0));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = {i[2:0], i[8:3]};

  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  assign h0 = q[8];
endmodule
