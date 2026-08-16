// One-bit External-AHB retention discriminator.
//
// This keeps the silicon-qualified posted-capture lane-0 boundary exactly:
// HWDATA0 terminates at X14Y12_SLICE15 and that register's Q drives HRDATA0.
// The only new storage mechanism is an external identity LUT in the feedback
// loop.  Consequently the state LUT does not consume its own Q directly and
// does not require one of the four direct-D sites.
//
// HREADYOUT is deliberately constant high.  A registered write token aligns
// the AHB address phase with HWDATA, and GPIO4.1 supplies the already-qualified
// synchronous fabric reset.  HRDATA1 mirrors the returned feedback value so a
// hardware oracle can require state and feedback to agree independently.
(* top *)
module top;
  wire hclk, htrans1, hwrite, reset_request;
  wire hwdata0, write_pending;
  wire state_q, feedback_f;
  wire hreadyout, hresp;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(state_q));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(feedback_f));

  // Registered address-phase write intent.  0808 implements
  // !reset_request && hwrite && htrans1 for I={0,reset,hwrite,htrans1}.
  // The BEL is the exact posted-capture16 write-stage footprint.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0808), .FF_USED(1'b1))
    write_stage(.CLK(hclk),
                .I({1'b0, reset_request, hwrite, htrans1}),
                .F(), .Q(write_pending));

  // 0B08 implements reset ? 0 : write_pending ? hwdata0 : feedback_f
  // for I={feedback_f,reset,write_pending,hwdata0}.  Both the HWDATA ingress
  // and HRDATA exit therefore retain the exact posted lane-0 endpoint.
  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture0(.CLK(hclk),
             .I({feedback_f, reset_request, write_pending, hwdata0}),
             .F(), .Q(state_q));

  // Explicit primitive + keep prevents synthesis from collapsing this back
  // into direct own-Q feedback.  The router may place it wherever the strict
  // graph provides state-Q -> I0 and F -> capture0-I3 paths.
  // X14Y10_SLICE0 is free in the complete posted-capture16 placement.  Pinning
  // the discriminator here avoids a misleading one-bit success that consumes
  // capture1's X14Y10_SLICE3 site and therefore cannot compose to 16 lanes.
  (* keep, BEL = "X14Y10_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    feedback_buffer(.CLK(hclk), .I({3'b000, state_q}),
                    .F(feedback_f), .Q());

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;
endmodule
