// Natural-placement HWDATA[4] capture under the qualified MCU bus clock.
// Silicon qualification of the routed image is required before its consumer
// site or corridor may enter the strict footprint table.
module top;
  wire hclk, hwdata4, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata4(.DIN(hwdata4));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(write_data_pipe));

  (* keep *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({3'b000, hwdata4}),
            .F(), .Q(write_data_pipe));
endmodule
