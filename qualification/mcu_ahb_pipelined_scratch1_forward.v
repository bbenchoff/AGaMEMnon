// One-bit posted-write oracle with read-after-write forwarding.
//
// The hard HWDATA lane still has exactly one unconditional registered
// consumer.  During the following bus cycle, write_commit identifies that
// captured value as the newest scratch state and forwards it to HRDATA while
// the physical scratch FF retires the same value one edge later.
module agamemnon_ahb_pipelined_scratch1_forward_core (
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
`ifdef SYNTHESIS
  wire scratch;
`else
  reg scratch;
`endif
  (* keep *) reg write_data_pipe;

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;
  // write_commit and write_data_pipe become valid together at the end of the
  // write data phase.  Forwarding is therefore visible during an immediately
  // following read data phase without exposing HWDATA combinationally.
`ifdef SYNTHESIS
  // Complete consumer footprint for the characterized X14Y11 slice5 data
  // source. OMUX16 reaches free slice14 I3/IMUX59. FC0C implements
  // write_commit ? write_data_pipe : scratch on I2/I3/I1 respectively.
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFC0C), .FF_USED(1'b0))
    forwarding_mux(.CLK(hclk),
                   .I({write_data_pipe, write_commit, scratch, 1'b0}),
                   .F(hrdata0), .Q());
`else
  assign hrdata0 = write_commit ? write_data_pipe : scratch;
`endif

`ifdef SYNTHESIS
  // Complete registered-storage footprint: commit on I0, data on I1, and
  // qualified own-Q feedback on I3. DD88 implements I0 ? I1 : I3.
  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage(.CLK(hclk),
                    .I({scratch, 1'b0, write_data_pipe, write_commit}),
                    .F(), .Q(scratch));
`endif

  always @(posedge hclk)
    write_data_pipe <= hwdata0;

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      write_commit <= 1'b0;
`ifndef SYNTHESIS
      scratch <= 1'b0;
`endif
    end else begin
      write_commit <= write_pending;
      write_pending <= htrans1 && hwrite;
`ifndef SYNTHESIS
      if (write_commit)
        scratch <= write_data_pipe;
`endif
    end
  end
endmodule

module top;
  wire hclk, htrans1, hwrite, hwdata0;
  wire hreadyout, hresp, hrdata0;
  wire forwarded_readback;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata0));

  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    forwarded_readback_buffer(.CLK(hclk), .I({3'b000, forwarded_readback}),
                              .F(hrdata0), .Q());

  agamemnon_ahb_pipelined_scratch1_forward_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .hwdata0(hwdata0), .reset_request(1'b0),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata0(forwarded_readback));
endmodule
