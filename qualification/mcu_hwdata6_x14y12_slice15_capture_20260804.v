// Silicon discriminator for the HWDATA[6] registered-consumer footprint.
//
// The input path is the selector-exact corridor recovered from the qualified
// 2026-07-14 group-1 image:
//   X13Y10_BufMUX08 -> InputMUX09 -> X14Y10_RMUX73 -> X14Y9_RMUX07
//   -> X14Y8_RMUX25 -> X14Y12_RMUX22 -> X14Y12_IMUX60.
// IMUX60 is physical X14Y12 slice15 I[0].  The registered result uses that
// site's established direct HRDATA[5] exit through RMUX86/BBMUXE07.
module top;
  wire bus_clock;
  wire hwdata6;
  wire captured;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep *) MCU_DIN mcu_hwdata6(.DIN(hwdata6));
  (* keep *)
  GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b1))
    capture(.CLK(bus_clock), .I({3'b000, hwdata6}), .F(), .Q(captured));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(captured));
endmodule
