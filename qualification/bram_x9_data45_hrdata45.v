// Paired-output discriminator for the x9 q5 hard-boundary footprint.
//
// q4 is the adjacent silicon-qualified lane.  Driving q4 and q5 together
// tests whether the odd lane depends on a shared output-group footprint that
// a one-lane open design leaves inactive.
module top(input clk);
  wire [3:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(ahb_word[3]));
  wire [9:0] addr = {6'b0, ahb_word};

  wire h4;
  wire h5;
  (* keep *) MCU_DOUT mcu_h4(.DOUT(h4));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(h5));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      // Both observed lanes must vary over the 16-address HADDR[5:2]
      // projection.  Complementary bit-3 patterns distinguish the two
      // physical outputs while keeping this a paired-conduction oracle.
      // Keep the other seven ROM planes nonconstant as well so synthesis
      // retains the nine-bit hard-BRAM width and its established x9
      // physical output mapping (q4/q5 -> DataOutA13/A14).
      mem[i] = {i[8:6], ~i[3], i[3], i[5], i[2:0]};
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  assign h4 = q[4];
  assign h5 = q[5];
endmodule
