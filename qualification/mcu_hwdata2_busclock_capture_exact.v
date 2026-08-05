// Exact-footprint HWDATA[2] capture under the qualified MCU bus clock.
//
// The retained group-0 write oracle qualified HWDATA[2] at X14Y11
// slice4/I0 and its OMUX14-to-HRDATA2 exit across 64 protocol-valid patterns.
// This discriminator retains one unconditional registered consumer.
module top;
  wire hclk, hwdata2, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata2));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(write_data_pipe));

  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({3'b000, hwdata2}),
            .F(), .Q(write_data_pipe));
endmodule
