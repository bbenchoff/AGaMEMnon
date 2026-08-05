module top;
  wire hclk, hwdata0, captured;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(captured));
  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCCCC), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({2'b00, hwdata0, 1'b0}), .F(), .Q(captured));
endmodule
