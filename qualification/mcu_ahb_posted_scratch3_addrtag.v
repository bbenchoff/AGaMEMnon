// Three-bit posted scratch register with one captured address tag.
//
// Lanes 0/1 retain the qualified capture-then-storage footprint. Lane 2 uses
// its qualified X14Y11 slice4 hard-input consumer as the storage FF itself:
// I0=HWDATA2, I1=the previous address-phase write token, I3=own Q.
module agamemnon_ahb_posted_scratch3_addrtag_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire [2:0] hwdata, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [2:0] hrdata
);
  (* keep, BEL = "X14Y12_SLICE1" *) reg write_pending;
  (* keep, BEL = "X14Y12_SLICE0" *) reg addr_pipe;
  (* keep *) reg [1:0] write_data_pipe;
`ifdef SYNTHESIS
  wire write_commit0;
  wire [2:0] scratch;
`else
  reg write_commit0;
  reg [2:0] scratch;
`endif

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;

`ifdef SYNTHESIS
  // I0=address tag, I1=write_pending. 0x4444 = I1 && !I0.
  (* keep, BEL = "X17Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h4444), .FF_USED(1'b1))
    write_commit_stage(.CLK(hclk),
                       .I({write_pending, addr_pipe, write_pending, addr_pipe}),
                       .F(), .Q(write_commit0));

  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5404), .FF_USED(1'b0))
    forwarding_mux0(.CLK(hclk),
                    .I({write_data_pipe[0], write_commit0,
                        scratch[0], addr_pipe}),
                    .F(hrdata[0]), .Q());
  (* keep, BEL = "X14Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h5404), .FF_USED(1'b0))
    forwarding_mux1(.CLK(hclk),
                    .I({write_data_pipe[1], write_commit0,
                        scratch[1], addr_pipe}),
                    .F(hrdata[1]), .Q());
  // Same-tile lane2 read footprint: I0 receives the slice4 state through the
  // qualified RMUX32/RMUX34 branch; live HADDR2 on I1 selects the AHB read
  // address. 0x2222 = I0 && !I1. Registered addr_pipe remains exclusively a
  // write-phase tag because two routes from its Q to this I3 were stuck high.
  (* keep, BEL = "X14Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2222), .FF_USED(1'b0))
    forwarding_mux2(.CLK(hclk), .I({2'b00, haddr2, scratch[2]}),
                    .F(hrdata[2]), .Q());

  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage0(.CLK(hclk),
                     .I({scratch[0], 1'b0,
                         write_data_pipe[0], write_commit0}),
                     .F(), .Q(scratch[0]));
  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage1(.CLK(hclk),
                     .I({scratch[1], 1'b0,
                         write_data_pipe[1], write_commit0}),
                     .F(), .Q(scratch[1]));
  // I0=HWDATA2, I1=the already-address-qualified commit, I3=own Q.
  // 0xBB88 = I1 ? I0 : I3. This keeps HWDATA2 on its exact qualified
  // physical I0 while matching the proven commit-then-storage architecture
  // of lanes 0/1; the failed folded pending/address footprint is not reused.
  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBB88), .FF_USED(1'b1))
    scratch_storage2(.CLK(hclk),
                     .I({scratch[2], 1'b0, write_commit0, hwdata[2]}),
                     .F(), .Q(scratch[2]));
`else
  assign hrdata = addr_pipe ? 3'b000 :
                  {scratch[2],
                   (write_commit0 ? write_data_pipe[1] : scratch[1]),
                   (write_commit0 ? write_data_pipe[0] : scratch[0])};
`endif

  always @(posedge hclk)
    write_data_pipe <= hwdata[1:0];

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
`ifndef SYNTHESIS
      write_commit0 <= 1'b0;
`endif
      addr_pipe <= 1'b0;
`ifndef SYNTHESIS
      scratch <= 3'b000;
`endif
    end else begin
`ifndef SYNTHESIS
      if (write_pending && !addr_pipe)
        scratch[2] <= hwdata[2];
      if (write_commit0)
        scratch[1:0] <= write_data_pipe;
`endif
`ifndef SYNTHESIS
      write_commit0 <= write_pending && !addr_pipe;
`endif
      write_pending <= htrans1 && hwrite;
      addr_pipe <= haddr2;
    end
  end
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2;
  wire [2:0] hwdata, readback;
  wire hrdata0, hreadyout, hresp;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata[0]));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata[1]));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata[2]));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(readback[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(readback[2]));
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    readback_buffer0(.CLK(hclk), .I({3'b000, readback[0]}),
                     .F(hrdata0), .Q());
  agamemnon_ahb_posted_scratch3_addrtag_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata(hwdata), .reset_request(1'b0), .hreadyout(hreadyout),
    .hresp(hresp), .hrdata(readback));
endmodule
