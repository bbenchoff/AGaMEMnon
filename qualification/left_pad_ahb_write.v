// Hardware qualification for left-edge output pads.  Firmware alternately
// writes 0 and 1 to external AHB address 0x60000000; this slave captures
// HWDATA[0] and drives the constrained package pin through a real register.
module top(input clk, output o);
  wire hwdata0, hwrite, htrans1, hrdata0;
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DOUT mcu_hrdata0(.DOUT(hrdata0));

  reg write_data_phase = 1'b0;
  reg output_state = 1'b0;
  always @(posedge clk) begin
    write_data_phase <= hwrite & htrans1;
    if (write_data_phase)
      output_state <= hwdata0;
  end

  // The silicon-positive vendor corridor is driven from the slice's F output,
  // with Q retained as local state.  Invert here so synthesis keeps a real LUT
  // output at the corridor source instead of bypassing it with a bare FF Q.
  assign o = ~output_state;
  assign hrdata0 = output_state;
endmodule
