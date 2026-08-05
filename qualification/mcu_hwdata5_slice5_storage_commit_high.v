module top;
  wire hclk, hwdata5, stored;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata5(.DIN(hwdata5));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(stored));
  // Same I0=commit, I1=data, I3=own-Q storage equation as the first six-bit
  // image, with commit tied high to remove its routed corridor.
  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    storage(.CLK(hclk), .I({stored, 1'b0, hwdata5, 1'b1}), .F(), .Q(stored));
endmodule
