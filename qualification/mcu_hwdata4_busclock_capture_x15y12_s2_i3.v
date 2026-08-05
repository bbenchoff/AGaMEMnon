module top;
  wire hclk, hwdata4, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata4(.DIN(hwdata4));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(write_data_pipe));
  (* keep, BEL = "X15Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({hwdata4, 3'b000}), .F(), .Q(write_data_pipe));
endmodule
