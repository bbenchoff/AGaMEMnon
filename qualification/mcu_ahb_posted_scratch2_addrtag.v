// Two-bit posted scratch register with one captured address tag.
//
// Offset 0 is writable/readable; offset 4 reads zero and ignores writes.
// Each hard HWDATA lane has exactly one unconditional registered consumer.
module agamemnon_ahb_posted_scratch2_addrtag_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire [1:0] hwdata, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [1:0] hrdata
);
  reg write_pending;
  reg write_commit0;
  reg addr_pipe;
  (* keep *) reg [1:0] write_data_pipe;
`ifdef SYNTHESIS
  wire [1:0] scratch;
`else
  reg [1:0] scratch;
`endif

  assign hreadyout = 1'b1;
  assign hresp = 1'b0;

`ifdef SYNTHESIS
  // I3=data, I2=commit0, I1=scratch, I0=read-address tag.
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

  // I3=own Q, I1=data, I0=commit. 0xDD88 = I0 ? I1 : I3.
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
`else
  assign hrdata = addr_pipe ? 2'b00 :
                  (write_commit0 ? write_data_pipe : scratch);
`endif

  always @(posedge hclk)
    write_data_pipe <= hwdata;

  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      write_commit0 <= 1'b0;
      addr_pipe <= 1'b0;
`ifndef SYNTHESIS
      scratch <= 2'b00;
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
  wire hclk, htrans1, hwrite, haddr2;
  wire [1:0] hwdata, readback;
  wire hrdata0;
  wire hreadyout, hresp;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata[0]));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata[1]));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata0));
  // Lane 1 uses the forwarding LUT's F output directly. The automatic
  // X14Y8 slice8 identity placement is not valid unless its characterized
  // X15Y8_RMUX00 final edge is also present as a complete footprint.
  (* keep *) MCU_DOUT mcu_h1(.DOUT(readback[1]));
  (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
    readback_buffer0(.CLK(hclk), .I({3'b000, readback[0]}),
                     .F(hrdata0), .Q());
  agamemnon_ahb_posted_scratch2_addrtag_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata(hwdata), .reset_request(1'b0), .hreadyout(hreadyout),
    .hresp(hresp), .hrdata(readback));
endmodule
