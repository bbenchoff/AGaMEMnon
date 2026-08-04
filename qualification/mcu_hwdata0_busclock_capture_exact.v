// Exact-footprint HWDATA[0] capture under the qualified MCU bus clock.
//
// The retained group-0 oracle qualified HWDATA[0] at X14Y11 slice5/I1 and
// its OMUX17-to-HRDATA0 exit across 64 protocol-valid patterns.  This narrow
// discriminator changes only the clock source to MCU_BUS_CLOCK, keeping one
// unconditional registered consumer and the same hard readback lane.
module top;
  wire hclk, hwdata0, write_data_pipe;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(write_data_pipe));

  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hCCCC), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({2'b00, hwdata0, 1'b0}),
            .F(), .Q(write_data_pipe));
endmodule
