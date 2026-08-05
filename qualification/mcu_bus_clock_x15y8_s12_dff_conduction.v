// Same-site discriminator for the X15Y8 slice12 register-bank frontier.
// A qualified X14Y11 slice7 TFF supplies changing D; the candidate site is
// only an ordinary registered consumer, so no direct-D self-feedback field is
// required at X15Y8. Both states isolate bus-clock/register/output conduction
// from the failed coordinate-substituted direct-D footprint experiment.
module top;
  wire bus_clock;
  wire source_q;
  wire source_f;
  wire captured;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));

  (* keep, BEL="X14Y11_SLICE7", agamemnon_direct_d_feedback="1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00ff), .FF_USED(1'b1))
    source_tff(.CLK(bus_clock), .I({source_q, 3'b000}),
               .F(source_f), .Q(source_q));

  (* keep, BEL="X15Y8_SLICE12" *)
  GENERIC_SLICE #(.K(4), .INIT(16'haaaa), .FF_USED(1'b1))
    candidate_dff(.CLK(bus_clock), .I({3'b000, source_q}),
                  .F(), .Q(captured));

  (* keep *) MCU_DOUT mcu_h0(.DOUT(captured));
endmodule
