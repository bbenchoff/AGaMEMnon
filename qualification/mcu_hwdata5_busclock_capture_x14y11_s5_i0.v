module top;
  wire hclk, hwdata5, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata5(.DIN(hwdata5));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(write_data_pipe));
  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({3'b000, hwdata5}), .F(), .Q(write_data_pipe));
endmodule
