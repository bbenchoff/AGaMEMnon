// Long-period bus-clock state with a software-controlled, synchronous reset.
module top;
  wire bus_clock;
  wire reset_request;
  reg [15:0] state = 16'h0000;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep *) MCU mcu_reset_control(.DIN(reset_request));

  always @(posedge bus_clock) begin
    if (reset_request)
      state <= 16'h0000;
    else
      state <= {state[14:0], ~(state[15] ^ state[13] ^ state[12] ^ state[10])};
  end

  (* keep *) MCU_DOUT mcu_h0(.DOUT(state[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(state[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(state[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(state[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(state[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(state[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(state[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(state[7]));
  (* keep *) MCU_DOUT mcu_h8(.DOUT(state[8]));
  (* keep *) MCU_DOUT mcu_h9(.DOUT(state[9]));
  (* keep *) MCU_DOUT mcu_h10(.DOUT(state[10]));
  (* keep *) MCU_DOUT mcu_h11(.DOUT(state[11]));
  (* keep *) MCU_DOUT mcu_h12(.DOUT(state[12]));
  (* keep *) MCU_DOUT mcu_h13(.DOUT(state[13]));
  (* keep *) MCU_DOUT mcu_h14(.DOUT(state[14]));
  (* keep *) MCU_DOUT mcu_h15(.DOUT(state[15]));
endmodule
