// Five-bit posted scratch register with one captured write-address tag.
module agamemnon_ahb_posted_scratch5_addrtag_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire [4:0] hwdata, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [4:0] hrdata
);
  (* keep, BEL = "X14Y12_SLICE1" *) reg write_pending;
  (* keep, BEL = "X14Y12_SLICE0" *) reg addr_pipe;
  (* keep *) reg [1:0] write_data_pipe;
`ifdef SYNTHESIS
  wire write_commit0;
  wire [4:0] scratch;
`else
  reg write_commit0;
  reg [4:0] scratch;
`endif

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;

`ifdef SYNTHESIS
  (* keep, BEL = "X17Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h4444), .FF_USED(1'b1))
    write_commit_stage(.CLK(hclk),
                       .I({2'b00, write_pending, addr_pipe}),
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
  (* keep, BEL = "X14Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2222), .FF_USED(1'b0))
    forwarding_mux2(.CLK(hclk), .I({2'b00, haddr2, scratch[2]}),
                    .F(hrdata[2]), .Q());
  (* keep, BEL = "X14Y11_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2222), .FF_USED(1'b0))
    forwarding_mux3(.CLK(hclk), .I({2'b00, haddr2, scratch[3]}),
                    .F(hrdata[3]), .Q());
  (* keep, BEL = "X14Y11_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2222), .FF_USED(1'b0))
    forwarding_mux4(.CLK(hclk), .I({2'b00, haddr2, scratch[4]}),
                    .F(hrdata[4]), .Q());

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
  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBB88), .FF_USED(1'b1))
    scratch_storage2(.CLK(hclk),
                     .I({scratch[2], 1'b0, write_commit0, hwdata[2]}),
                     .F(), .Q(scratch[2]));
  // 0xDD88 = I0(commit) ? I1(HWDATA3) : I3(own Q). HWDATA3 remains
  // on its exact X15Y12 slice0/I1 consumer terminal.
  (* keep, BEL = "X15Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage3(.CLK(hclk),
                     .I({scratch[3], 1'b0, hwdata[3], write_commit0}),
                     .F(), .Q(scratch[3]));
  // X15Y12 slice2/I1 is qualified for HWDATA4; I0 remains the commit input
  // and I3 carries the same direct-D feedback equation as lane3.
  (* keep, BEL = "X15Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    scratch_storage4(.CLK(hclk),
                     .I({scratch[4], 1'b0, hwdata[4], write_commit0}),
                     .F(), .Q(scratch[4]));
`else
  assign hrdata = haddr2 ? 5'b00000 :
                  {scratch[4:2],
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
      scratch <= 4'b0000;
`endif
    end else begin
`ifndef SYNTHESIS
      if (write_pending && !addr_pipe)
        scratch[4:2] <= hwdata[4:2];
      if (write_commit0)
        scratch[1:0] <= write_data_pipe;
      write_commit0 <= write_pending && !addr_pipe;
`endif
      write_pending <= htrans1 && hwrite;
      addr_pipe <= haddr2;
    end
  end
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2;
  wire [4:0] hwdata, readback;
  wire hrdata0, hreadyout, hresp;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata[0]));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata[1]));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata[2]));
  (* keep *) MCU_DIN mcu_hwdata3(.DIN(hwdata[3]));
  (* keep *) MCU_DIN mcu_hwdata4(.DIN(hwdata[4]));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata0));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(readback[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(readback[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(readback[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(readback[4]));
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    readback_buffer0(.CLK(hclk), .I({3'b000, readback[0]}),
                     .F(hrdata0), .Q());
  agamemnon_ahb_posted_scratch5_addrtag_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata(hwdata), .reset_request(1'b0), .hreadyout(hreadyout),
    .hresp(hresp), .hrdata(readback));
endmodule
