// Isolated x9 logical data-bit5 corridor from the working vendor control.
// See bram_x9_data4_hrdata4.v for the experiment design rationale.
module top(input clk);
  wire [3:0] ahb_word;
  (* keep *) MCU_DIN mcu_haddr2(.DIN(ahb_word[0]));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(ahb_word[1]));
  (* keep *) MCU_DIN mcu_haddr4(.DIN(ahb_word[2]));
  (* keep *) MCU_DIN mcu_haddr5(.DIN(ahb_word[3]));
  wire [9:0] addr = {6'b0, ahb_word};

  wire h5;
  (* keep *) MCU_DOUT mcu_h5(.DOUT(h5));

  reg [8:0] mem [0:1023];
  integer i;
  initial
    for (i = 0; i < 1024; i = i + 1)
      mem[i] = {i[8:6], i[3], i[4], i[5], i[2:0]};
  reg [8:0] q;
  always @(posedge clk)
    q <= mem[addr];

  assign h5 = q[5];
endmodule
