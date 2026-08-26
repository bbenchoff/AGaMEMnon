// MCU-readable arm for the bounded exact-source fabric AHB read observer.
//
// One read-only fabric-master transfer is emitted when the MCU first reads the
// endpoint or changes HADDR[2]. Repeated reads at one command address only
// observe the retained response; they cannot create background bus traffic.
// The
// External-AHB slave port exposes only three raw diagnostic bits:
//   bit 0: sampled HREADYOUT ^ HRESP ^ HRDATA[0]
//   bit 1: master busy
//   bit 2: one-cycle master done pulse
//   bit 3: at least one response has been sampled
// No other read-data lane is driven, and this endpoint intentionally ignores
// writes.  A host observer must sample a sequence rather than treating one
// asynchronous status word as an independent response-field capture.
module agamemnon_fabric_ahb_read_observer_endpoint #(
  parameter REQUEST_ENABLE = 1'b1
) ();
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
  reg start_pulse;
  reg command_latched;
  reg latched_word_select;

  (* keep *) agamemnon_fabric_ahb_read_master_ag32_sram_base master(
    .start(start_pulse),
    .word_select(command_word_select),
    .busy(busy),
    .done(done),
    .response_observation(response_observation),
    .response_sampled(response_sampled),
    .response_valid(response_valid),
    .fabric_clock(fabric_clock),
    .fabric_resetn(fabric_resetn)
  );

  // A command is a real External-AHB transfer, not an address level alone.
  // Latching the selected word means hundreds of status polls at one address
  // still produce exactly one fabric-master request. A 0->1 or 1->0 address
  // transition admits one further bounded request.
  always @(posedge fabric_clock) begin
    if (!fabric_resetn) begin
      start_pulse <= 1'b0;
      command_latched <= 1'b0;
      latched_word_select <= 1'b0;
    end else begin
      start_pulse <= 1'b0;
      if (!REQUEST_ENABLE) begin
        command_latched <= 1'b0;
      end else if (command_htrans1 && !busy &&
                   (!command_latched ||
                    command_word_select != latched_word_select)) begin
        start_pulse <= 1'b1;
        command_latched <= 1'b1;
        latched_word_select <= command_word_select;
      end
    end
  end

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
