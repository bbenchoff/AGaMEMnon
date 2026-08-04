// One-bit posted store with one captured address tag.
//
// Address 0 is writable/readable; address 1 reads zero and ignores writes.
// HADDR[2] has one unconditional registered consumer, avoiding hard-input
// fanout.  The delayed write token combines with the previous address tag so
// forwarding occurs only for the writable register.
module agamemnon_ahb_posted_scratch1_addrtag_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire hwdata0, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire hrdata0
);
  reg write_pending;
  reg write_commit0;
  reg addr_pipe;
  (* keep *) reg write_data_pipe;
`ifdef SYNTHESIS
  wire scratch;
`else
  reg scratch;
`endif

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;

`ifdef SYNTHESIS
  // I3=data, I2=commit0, I1=scratch, I0=read-address tag.
  // 0x5404 = addr_pipe ? 0 : (write_commit0 ? data : scratch).
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5404), .FF_USED(1'b0))
    forwarding_mux(.CLK(hclk),
                   .I({write_data_pipe, write_commit0, scratch, addr_pipe}),
                   .F(hrdata0), .Q());
  // Complete registered storage footprint: commit on I0, data on I1, and
  // own-Q feedback on I3. 0xDD88 = I0 ? I1 : I3.
  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage(.CLK(hclk),
                    .I({scratch, 1'b0, write_data_pipe, write_commit0}),
                    .F(), .Q(scratch));
`else
  assign hrdata0 = addr_pipe ? 1'b0 :
                   (write_commit0 ? write_data_pipe : scratch);
`endif

  always @(posedge hclk)
    write_data_pipe <= hwdata0;

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      write_commit0 <= 1'b0;
      addr_pipe <= 1'b0;
`ifndef SYNTHESIS
      scratch <= 1'b0;
`endif
    end else begin
      write_commit0 <= write_pending && !addr_pipe;
      write_pending <= htrans1 && hwrite;
      addr_pipe <= haddr2;
`ifndef SYNTHESIS
      if (write_commit0)
        scratch <= write_data_pipe;
`endif
    end
  end
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2, hwdata0;
  wire hreadyout, hresp, readback, hrdata0;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata0));
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    readback_buffer(.CLK(hclk), .I({3'b000, readback}), .F(hrdata0), .Q());
  agamemnon_ahb_posted_scratch1_addrtag_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata0(hwdata0), .reset_request(1'b0), .hreadyout(hreadyout),
    .hresp(hresp), .hrdata0(readback));
endmodule
