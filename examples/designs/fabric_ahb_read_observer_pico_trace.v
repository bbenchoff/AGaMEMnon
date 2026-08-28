module top(output wire [3:0] trace);
  wire raw_start_pulse;
  wire raw_command_pending;
  wire raw_busy;
  wire raw_response_sampled;
  wire fabric_clock;

  wire trace_start_pulse;
  wire trace_command_pending;
  wire trace_busy;
  wire trace_response_sampled;

  agamemnon_fabric_ahb_read_observer_endpoint #(
    .REQUEST_ENABLE(1'b1)
  ) dut(
    .trace_start_pulse(raw_start_pulse),
    .trace_command_pending(raw_command_pending),
    .trace_busy(raw_busy),
    .trace_response_sampled(raw_response_sampled),
    .trace_fabric_clock(fabric_clock)
  );

  (* keep, BEL="X14Y11_SLICE4" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_start_pulse_ff(
    .CLK(fabric_clock), .I({3'b000, raw_start_pulse}), .F(), .Q(trace_start_pulse));
  (* keep, BEL="X14Y11_SLICE5" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_command_pending_ff(
    .CLK(fabric_clock), .I({3'b000, raw_command_pending}), .F(),
    .Q(trace_command_pending));
  (* keep, BEL="X14Y11_SLICE6" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_busy_ff(
    .CLK(fabric_clock), .I({3'b000, raw_busy}), .F(), .Q(trace_busy));
  (* keep, BEL="X14Y11_SLICE7" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_response_sampled_ff(
    .CLK(fabric_clock), .I({3'b000, raw_response_sampled}), .F(),
    .Q(trace_response_sampled));

  assign trace = {
    trace_response_sampled,
    trace_busy,
    trace_command_pending,
    trace_start_pulse
  };
endmodule
