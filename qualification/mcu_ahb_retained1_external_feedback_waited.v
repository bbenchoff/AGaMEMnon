// Waited one-bit External-AHB retention discriminator.
//
// The storage loop is identical to mcu_ahb_retained1_external_feedback.v.
// The only architectural change is the complete-byte bank's silicon-qualified
// one-wait handshake: the write token at X14Y12_SLICE1 is admitted only while
// ready, and X14Y11_SLICE6 drives HREADYOUT low for the token's data phase.
(* top *)
module top;
  wire hclk, htrans1, hwrite, reset_request;
  wire hwdata0, write_pending, write_ready_f;
  wire state_q, feedback_f;
  wire hresp;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(write_ready_f));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(state_q));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(feedback_f));

  // Exact qualified one-wait token.  For
  // I={reset,ready,hwrite,htrans1}, 0080 implements
  // !reset && ready && hwrite && htrans1.
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0080), .FF_USED(1'b1))
    write_stage(.CLK(hclk),
                .I({reset_request, write_ready_f, hwrite, htrans1}),
                .F(), .Q(write_pending));

  // Exact qualified response source/corridor. DDDD implements
  // reset_request || !write_pending for I={0,0,reset,write_pending}.
  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDDDD), .FF_USED(1'b0))
    write_wait_stage(.CLK(hclk),
                     .I({2'b00, reset_request, write_pending}),
                     .F(write_ready_f), .Q());

  // Storage, HWDATA endpoint and HRDATA state endpoint are unchanged from the
  // two constant-ready token negatives.  During the inserted wait HWDATA is
  // held stable, and write_pending is the commit level sampled by this FF.
  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture0(.CLK(hclk),
             .I({feedback_f, reset_request, write_pending, hwdata0}),
             .F(), .Q(state_q));

  (* keep, BEL = "X14Y10_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    feedback_buffer(.CLK(hclk), .I({3'b000, state_q}),
                    .F(feedback_f), .Q());

  assign hresp = 1'b0;
endmodule
