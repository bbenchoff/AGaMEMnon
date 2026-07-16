// Four MCU-controlled LEDs for the AGRV2KL48 board. Each protocol-valid write
// to External AHB address 0x60000000 advances a visible Johnson pattern. This
// deliberately uses only the qualified HWRITE/HTRANS entry roots rather than
// requiring four simultaneous HWDATA routes.
module top(input clk, output [3:0] led);
  wire hwrite, htrans1;
  reg write_data_phase = 1'b0;
  reg [3:0] state = 4'b0;

  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));

  always @(posedge clk) begin
    write_data_phase <= hwrite & htrans1;
    if (write_data_phase)
      state <= {state[2:0], ~state[3]};
  end

  assign led = state;
endmodule
