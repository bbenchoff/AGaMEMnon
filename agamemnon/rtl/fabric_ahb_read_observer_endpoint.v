// MCU-readable arm for the bounded exact-source fabric AHB read observer.
//
// One read-only fabric-master transfer is armed when the MCU first reads the
// endpoint or changes HADDR[2], then emitted only after the originating
// HTRANS[1] deasserts. Repeated reads at one command address only observe the
// retained response; they cannot create background bus traffic. The
// External-AHB slave port exposes only four raw diagnostic bits:
//   bit 0: sampled HREADYOUT ^ HRESP ^ HRDATA[0]
//   bit 1: master busy
//   bit 2: one-cycle master done pulse
//   bit 3: at least one response has been sampled
// No other read-data lane is driven, and this endpoint intentionally ignores
// writes.  A host observer must sample a sequence rather than treating one
// asynchronous status word as an independent response-field capture.
module agamemnon_fabric_ahb_read_observer_endpoint #(
  parameter REQUEST_ENABLE = 1'b1,
  parameter TRACE_STATE_OUTPUT = 1'b0
) (
  output wire       trace_start_pulse,
  output wire       trace_command_pending,
  output wire [1:0] trace_master_state,
  output wire       trace_busy,
  output wire       trace_done,
  output wire       trace_response_sampled,
  output wire       trace_response_valid,
  output wire       trace_fabric_clock
);
  wire busy;
  wire done;
  wire response_observation;
  wire response_sampled;
  wire response_valid;
  wire command_word_select;
  wire command_htrans1;
  wire endpoint_ready;
  wire endpoint_okay;
  wire fabric_clock;
  wire fabric_resetn;
  wire [1:0] master_state;
  wire request_arm;
  wire start_pulse;
  wire command_latched;
  wire command_pending;
  wire latched_word_select;
  (* keep *) reg next_start_pulse;
  (* keep *) reg next_command_latched;
  (* keep *) reg next_command_pending;
  (* keep *) reg next_latched_word_select;

  (* keep *) agamemnon_fabric_ahb_read_master_ag32_sram_base #(
    .TRACE_STATE_OUTPUT(TRACE_STATE_OUTPUT)
  ) master(
    .start(start_pulse),
    .word_select(latched_word_select),
    .busy(busy),
    .done(done),
    .response_observation(response_observation),
    .response_sampled(response_sampled),
    .response_valid(response_valid),
    .debug_state(master_state),
    .fabric_clock(fabric_clock),
    .fabric_resetn(fabric_resetn)
  );

  assign trace_start_pulse = start_pulse;
  assign trace_command_pending = command_pending;
  assign trace_master_state = master_state;
  assign trace_busy = busy;
  assign trace_done = done;
  assign trace_response_sampled = response_sampled;
  assign trace_response_valid = response_valid;
  assign trace_fabric_clock = fabric_clock;

  // Keep the launch arm as a real routed LUT. R3 derives its route-identical
  // control by changing only this INIT from ffff to 0000 after routing.
  (* keep *) LUT #(
    .K(4), .INIT(REQUEST_ENABLE ? 16'hffff : 16'h0000)
  ) request_arm_source(.I(4'b0000), .Q(request_arm));

  // A command is a real External-AHB transfer, not an address level alone.
  // First latch it as pending. Launch only after HTRANS[1] deasserts, so the
  // fabric master cannot recursively start on the originating MCU slave-read
  // edge. Same-address polls stay passive; a 0->1 or 1->0 transition re-arms.
  // Express reset and hold as ordinary data selection so every physical FF
  // retains the qualified plain-positive-edge shared-control signature.
  always @* begin
    next_start_pulse = 1'b0;
    next_command_latched = command_latched;
    next_command_pending = command_pending;
    next_latched_word_select = latched_word_select;
    if (!fabric_resetn) begin
      next_start_pulse = 1'b0;
      next_command_latched = 1'b0;
      next_command_pending = 1'b0;
      next_latched_word_select = 1'b0;
    end else begin
      if (!request_arm) begin
        next_command_latched = 1'b0;
        next_command_pending = 1'b0;
      end else begin
        if (command_pending && !command_htrans1 && !busy) begin
          next_start_pulse = 1'b1;
          next_command_pending = 1'b0;
        end
        if (command_htrans1 && !busy && !command_pending &&
            (!command_latched ||
             command_word_select != latched_word_select)) begin
          next_command_latched = 1'b1;
          next_command_pending = 1'b1;
          next_latched_word_select = command_word_select;
        end
      end
    end
  end

  (* keep *) GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) start_pulse_ff(
    .CLK(fabric_clock), .I({3'b000, next_start_pulse}), .F(), .Q(start_pulse));
  (* keep *) GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) command_latched_ff(
    .CLK(fabric_clock), .I({3'b000, next_command_latched}), .F(), .Q(command_latched));
  (* keep *) GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) command_pending_ff(
    .CLK(fabric_clock), .I({3'b000, next_command_pending}), .F(), .Q(command_pending));
  (* keep *) GENERIC_SLICE #(.INIT(16'hAAAA), .FF_USED(1)) latched_word_select_ff(
    .CLK(fabric_clock), .I({3'b000, next_latched_word_select}), .F(),
    .Q(latched_word_select));

  // Keep the response controls on independent local sources, matching the
  // qualified External-AHB endpoint composition.
  (* keep *) LUT #(.K(4), .INIT(16'hffff)) endpoint_ready_source(
    .I(4'b0000), .Q(endpoint_ready));
  (* keep *) LUT #(.K(4), .INIT(16'h0000)) endpoint_okay_source(
    .I(4'b0000), .Q(endpoint_okay));
  (* keep *) MCU_AHB_HREADYOUT endpoint_hreadyout(.DOUT(endpoint_ready));
  (* keep *) MCU_AHB_HRESP endpoint_hresp(.DOUT(endpoint_okay));

  // External-AHB HTRANS[1] qualifies the command and address bit 2 selects the
  // admitted SRAM word. Reads at 0x60000000 and 0x60000004 therefore request
  // word 0 and word 1 without changing the image or adding a write path.
  (* keep *) MCU_DIN command_haddr2(.DIN(command_word_select));
  (* keep *) MCU_DIN command_htrans1_input(.DIN(command_htrans1));

  // Conventional h<lane> leaf names make the packer bind the exact
  // External-AHB read-data lanes rather than choosing an arbitrary MCU_DOUT.
  (* keep *) MCU_DOUT observer_h0(.DOUT(response_sampled));
  (* keep *) MCU_DOUT observer_h1(.DOUT(busy));
  (* keep *) MCU_DOUT observer_h2(.DOUT(done));
  (* keep *) MCU_DOUT observer_h3(.DOUT(response_valid));
endmodule
