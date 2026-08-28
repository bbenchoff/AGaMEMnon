module top(output wire [3:0] trace);
  wire [1:0] raw_master_state;
  wire fabric_clock;
  wire [1:0] first_master_state;
  wire [1:0] second_master_state;

  agamemnon_fabric_ahb_read_observer_endpoint #(
    .REQUEST_ENABLE(1'b1)
  ) dut(
    .trace_master_state(raw_master_state),
    .trace_fabric_clock(fabric_clock)
  );

  // R10 deliberately leaves the R8 master FSM and its unconstrained state
  // flops untouched.  These are the same first registered copies used by R8.
  (* keep, BEL="X14Y11_SLICE4" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) first_master_state0_ff(
    .CLK(fabric_clock), .I({3'b000, raw_master_state[0]}), .F(),
    .Q(first_master_state[0]));
  (* keep, BEL="X14Y11_SLICE5" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) first_master_state1_ff(
    .CLK(fabric_clock), .I({3'b000, raw_master_state[1]}), .F(),
    .Q(first_master_state[1]));

  // A second same-clock stage observes only the first-stage Q values.  It
  // cannot add placement authority to, or feed back into, the functional FSM.
  (* keep, BEL="X14Y11_SLICE6" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) second_master_state0_ff(
    .CLK(fabric_clock), .I({3'b000, first_master_state[0]}), .F(),
    .Q(second_master_state[0]));
  (* keep, BEL="X14Y11_SLICE7" *)
  GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) second_master_state1_ff(
    .CLK(fabric_clock), .I({3'b000, first_master_state[1]}), .F(),
    .Q(second_master_state[1]));

  // CAP8 base 12 maps trace[0:3] to GP12, GP13, GP16, and GP17.
  assign trace = {
    second_master_state[1],
    second_master_state[0],
    first_master_state[1],
    first_master_state[0]
  };
endmodule
