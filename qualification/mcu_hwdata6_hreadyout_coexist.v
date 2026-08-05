// Bounded HWDATA6/HREADYOUT coexistence discriminator.
//
// HWDATA6 is qualified only as the registered X14Y12 slice15/I0 consumer.
// The six-bit posted bank also anchors its constant-high HREADYOUT source at
// that slice.  Keep both hard endpoints live here before widening the bank;
// a build failure is a resource-allocation boundary, not an electrical claim.
module top;
  wire hclk;
  wire hwdata6;
  wire captured;
  wire hreadyout = 1'b1;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_hwdata6(.DIN(hwdata6));
  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    capture(.CLK(hclk), .I({3'b000, hwdata6}), .F(), .Q(captured));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(captured));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
endmodule
