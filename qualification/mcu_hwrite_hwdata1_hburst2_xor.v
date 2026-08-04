// Isolated logic-ingress route oracle for one coherent AHB boundary triple.
module top;
  wire hwrite;
  wire hwdata1;
  wire hburst2;
  wire observed;

  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata1));
  (* keep *) MCU_AHB_HBURST2 mcu_hburst2(.DIN(hburst2));

  // I[1:3] map to the vendor-observed IMUX01/02/03 terminals at slice0.
  (* keep, BEL="X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hc33c), .FF_USED(1'b0))
    ingress(.I({hburst2, hwrite, hwdata1, 1'b0}), .F(observed));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(observed));
endmodule
