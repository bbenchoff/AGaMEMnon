// Minimal silicon oracle for the authorized pipelined HWDATA boundary.
//
// This is deliberately one writable bit rather than the full register bank:
// its state-holding control/data cells fit the currently qualified
// X14Y11 slice4:7 direct-D pool.  It proves AHB phase timing and the
// hard-HWDATA -> unconditional FF -> fabric-state boundary without implying
// wider storage, address decode, wait/error breadth, or hard reset delivery.
module agamemnon_ahb_pipelined_scratch1_core (
  input  wire hclk,
  input  wire htrans1,
  input  wire hwrite,
  input  wire hwdata0,
  input  wire reset_request,
  output wire hreadyout,
  output wire hresp,
  output wire hrdata0
);
  reg write_pending;
  reg write_commit;
  reg scratch;
  (* keep *) reg write_data_pipe;

  // Match the vendor bridge phase boundary: a new address is accepted while
  // this slave's own HREADYOUT is high.  HREADY is intentionally absent from
  // this first oracle, so no unqualified hard-HREADY logic corridor is used.
  wire accept = htrans1;
  // This first integrated boundary is the authorized posted-write variant:
  // the bus completes without a wait while the fabric retires the registered
  // data one cycle later.  Registered HREADYOUT modulation remains a separate
  // unqualified response-corridor unit.
  assign hreadyout = 1'b1;
  assign hresp = 1'b0;
  // AHB slaves may drive HRDATA continuously; the master samples it only in
  // the valid read data phase.  Avoiding a redundant read-phase mux also
  // avoids asserting an unqualified scratch-Q -> arbitrary-LUT corridor.
  assign hrdata0 = scratch;

  // HWDATA has exactly one fabric consumer before this unconditional FF.
  always @(posedge hclk)
    write_data_pipe <= hwdata0;

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      write_commit <= 1'b0;
      scratch <= 1'b0;
    end else begin
      // Address intent and data are registered independently.  The posted
      // transfer completes at the bus boundary while write_commit retires
      // the captured data on the following fabric cycle; consecutive address
      // phases therefore form an uninterrupted pipeline.
      write_commit <= write_pending;
      write_pending <= accept && hwrite;
      if (write_commit)
        scratch <= write_data_pipe;
    end
  end
endmodule


module top;
  wire hclk, htrans1, hwrite, hwdata0;
  wire reset_request = 1'b0;
  wire hreadyout, hresp, scratch_readback, hrdata0;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  // Reset-to-state is a separate integration boundary.  GPIO4.1 synchronous
  // reset is qualified on the LFSR placement, but its corridor to this fixed
  // direct-D pool is not; keep this protocol oracle fail-closed on that claim.

  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_hrdata0(.DOUT(hrdata0));

  // Registered state is not assumed to reach every hard read-data lane
  // directly.  Use the characterized explicit-buffer footprint so both arcs
  // remain visible to the strict router and emitter.
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    scratch_readback_buffer(.CLK(hclk), .I({3'b000, scratch_readback}),
                            .F(hrdata0), .Q());

  agamemnon_ahb_pipelined_scratch1_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .hwdata0(hwdata0), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata0(scratch_readback));
endmodule
