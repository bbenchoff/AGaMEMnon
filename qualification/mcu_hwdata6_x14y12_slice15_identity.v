// Isolated combinational identity-buffer qualification for the retained
// HWDATA[6] ingress path.  This tests whether the positive registered-capture
// site can also serve as the one-per-lane fanout root required by the full
// register bank; no generic route-through claim follows from a negative.
module top;
  wire hwdata6;
  wire observed;

  (* keep *) MCU_DIN mcu_hwdata6(.DIN(hwdata6));
  (* keep, BEL="X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b0))
    lane_buffer(.I({3'b000, hwdata6}), .F(observed));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(observed));
endmodule
