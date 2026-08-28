module top(output wire [3:0] trace);
  wire [1:0] raw_master_state;
  wire fabric_clock;
  wire [1:0] registered_master_state;

  agamemnon_fabric_ahb_read_observer_endpoint #(
    .REQUEST_ENABLE(1'b1),
    .TRACE_STATE_OUTPUT(1'b1)
  ) dut(
    .trace_master_state(raw_master_state),
    .trace_fabric_clock(fabric_clock)
  );

  // R9 compares each master-state bit before and after one same-clock trace
  // register.  R8 observed a repeated 01 -> 10 sequence even though the RTL
  // contains 01 -> 11 -> 10.  Carrying both views in the same capture
  // distinguishes an upstream master-state failure from a trace-register or
  // shared-clock sampling failure without inferring response behavior.
  (* keep, BEL="X14Y11_SLICE6" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) registered_master_state0_ff(
    .CLK(fabric_clock), .I({3'b000, raw_master_state[0]}), .F(),
    .Q(registered_master_state[0]));
  (* keep, BEL="X14Y11_SLICE7" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) registered_master_state1_ff(
    .CLK(fabric_clock), .I({3'b000, raw_master_state[1]}), .F(),
    .Q(registered_master_state[1]));

  // CAP8 base 12 maps trace[0:3] to GP12, GP13, GP16, and GP17.
  assign trace = {
    registered_master_state[1],
    registered_master_state[0],
    raw_master_state[1],
    raw_master_state[0]
  };
endmodule
