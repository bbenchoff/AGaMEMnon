module top(output wire [3:0] trace);
  wire raw_start_pulse;
  wire raw_command_pending;
  wire raw_busy;
  wire raw_response_sampled;
  wire fabric_clock;

  (* keep, BEL="X14Y11_SLICE4" *) reg trace_start_pulse;
  (* keep, BEL="X14Y11_SLICE5" *) reg trace_command_pending;
  (* keep, BEL="X14Y11_SLICE6" *) reg trace_busy;
  (* keep, BEL="X14Y11_SLICE7" *) reg trace_response_sampled;

  agamemnon_fabric_ahb_read_observer_endpoint #(
    .REQUEST_ENABLE(1'b0)
  ) dut(
    .trace_start_pulse(raw_start_pulse),
    .trace_command_pending(raw_command_pending),
    .trace_busy(raw_busy),
    .trace_response_sampled(raw_response_sampled),
    .trace_fabric_clock(fabric_clock)
  );

  always @(posedge fabric_clock) begin
    trace_start_pulse <= raw_start_pulse;
    trace_command_pending <= raw_command_pending;
    trace_busy <= raw_busy;
    trace_response_sampled <= raw_response_sampled;
  end

  assign trace = {
    trace_response_sampled,
    trace_busy,
    trace_command_pending,
    trace_start_pulse
  };
endmodule
