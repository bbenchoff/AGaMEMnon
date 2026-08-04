// Isolated HWDATA[6] logic-ingress discriminator.
//
// This deliberately tests the vendor-observed X14Y10 slice1 I[3] identity
// route-through before admitting it as a register-bank consumer footprint.
module top;
  wire hwdata6;
  wire hrdata6;

  (* keep *) MCU_DIN mcu_hwdata6(.DIN(hwdata6));
  (* keep, BEL="X14Y10_SLICE1" *)
  LUT #(.K(4), .INIT(16'hff00)) identity(
    .I({hwdata6, 3'b000}),
    .Q(hrdata6)
  );
  (* keep *) MCU_DOUT mcu_h6(.DOUT(hrdata6));
endmodule
