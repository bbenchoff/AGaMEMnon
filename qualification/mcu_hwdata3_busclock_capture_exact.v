// Exact-footprint HWDATA[3] capture under the qualified MCU bus clock.
//
// The retained group-0 write oracle qualified HWDATA[3] at X15Y12
// slice0/I1 and its OMUX02-to-HRDATA3 exit across 64 protocol-valid
// patterns. This discriminator retains one unconditional registered consumer.
module top;
  wire hclk, hwdata3, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata3(.DIN(hwdata3));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(write_data_pipe));

  (* keep, BEL = "X15Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCCCC), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({2'b00, hwdata3, 1'b0}),
            .F(), .Q(write_data_pipe));
endmodule
