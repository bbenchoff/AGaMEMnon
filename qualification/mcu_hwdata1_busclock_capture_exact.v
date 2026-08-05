// Exact-footprint HWDATA[1] capture under the qualified MCU bus clock.
//
// The retained group-0 write oracle qualified HWDATA[1] at X14Y10
// slice3/I1 and its OMUX11-to-HRDATA1 exit across 64 protocol-valid
// patterns. This narrow discriminator changes only the clock source to
// MCU_BUS_CLOCK while retaining one unconditional registered consumer.
module top;
  wire hclk, hwdata1, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata1));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(write_data_pipe));

  (* keep, BEL = "X14Y10_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCCCC), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({2'b00, hwdata1, 1'b0}),
            .F(), .Q(write_data_pipe));
endmodule
