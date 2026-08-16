// Token-source A/B for mcu_ahb_retained1_external_feedback.v.
//
// Hardware on the posted-stage control (X14Y12_SLICE0) produced exact reset
// and state/feedback agreement but never wrote: immediate/poison/repeat were
// each wrong on the 64 one-valued patterns.  This variant changes ONE intended
// architectural variable: the registered AHB write token uses the
// silicon-qualified complete-byte-bank site X14Y12_SLICE1.  State, external
// feedback, HWDATA/HRDATA endpoints, INIT equations and constant response are
// otherwise identical.
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

  // Exact resettable write-token equation/site from the qualified complete
  // byte bank: Q <= !reset_request && hwrite && htrans1.
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0808), .FF_USED(1'b1))
    write_stage(.CLK(hclk),
                .I({1'b0, reset_request, hwrite, htrans1}),
                .F(), .Q(write_pending));

  // Exact posted lane-0 HWDATA endpoint and HRDATA state endpoint.
  // I={feedback_f,reset,write_pending,hwdata0}; INIT implements
  // reset ? 0 : write_pending ? hwdata0 : feedback_f.
  (* keep, BEL = "X14Y12_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0B08), .FF_USED(1'b1))
    capture0(.CLK(hclk),
             .I({feedback_f, reset_request, write_pending, hwdata0}),
             .F(), .Q(state_q));

  // Same composable feedback site as the s0-token control.  It is free in the
  // complete posted-capture16 placement.
  (* keep, BEL = "X14Y10_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    feedback_buffer(.CLK(hclk), .I({3'b000, state_q}),
                    .F(feedback_f), .Q());

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;
endmodule
