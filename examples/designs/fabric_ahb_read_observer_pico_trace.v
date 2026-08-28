module top(output wire [3:0] trace);
  wire raw_start_pulse;
  wire raw_command_pending;
  wire [1:0] raw_master_state;
  wire fabric_clock;

  wire trace_start_pulse;
  wire trace_command_pending;
  wire trace_master_state0;
  wire trace_master_state1;

  agamemnon_fabric_ahb_read_observer_endpoint #(
    .REQUEST_ENABLE(1'b1)
  ) dut(
    .trace_start_pulse(raw_start_pulse),
    .trace_command_pending(raw_command_pending),
    .trace_master_state(raw_master_state),
    .trace_fabric_clock(fabric_clock)
  );

  // Cross the S05 result at the four qualified output corridors: the two
  // master-state bits move onto the pads that already carried pending/start,
  // while pending/start move onto the two pads that remained low.  One capture
  // can therefore distinguish a stationary master from a quiet output path.
  (* keep, BEL="X14Y11_SLICE4" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_master_state0_ff(
    .CLK(fabric_clock), .I({3'b000, raw_master_state[0]}), .F(),
    .Q(trace_master_state0));
  (* keep, BEL="X14Y11_SLICE5" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_master_state1_ff(
    .CLK(fabric_clock), .I({3'b000, raw_master_state[1]}), .F(),
    .Q(trace_master_state1));
  (* keep, BEL="X14Y11_SLICE6" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_start_pulse_ff(
    .CLK(fabric_clock), .I({3'b000, raw_start_pulse}), .F(), .Q(trace_start_pulse));
  (* keep, BEL="X14Y11_SLICE7" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) trace_command_pending_ff(
    .CLK(fabric_clock), .I({3'b000, raw_command_pending}), .F(),
    .Q(trace_command_pending));

  assign trace = {
    trace_command_pending,
    trace_start_pulse,
    trace_master_state1,
    trace_master_state0
  };
endmodule
