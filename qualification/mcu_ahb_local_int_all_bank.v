// Silicon-qualified one-image causes 16..19 command bank.
//
// The silicon-qualified cause-16 composite command state is shared by one
// selected local-interrupt lane.  HWDATA[3:2] selects one of four exact,
// already-qualified output corridors. HADDR2 selects the command class and
// HWDATA[1:0] commands remain:
//   00 = mask off / pending hold
//   01 = mask on  / acknowledge
//   10 = mask off / set
//   11 = mask on  / set
// Reads fail closed to zero. This interface deliberately uses one shared
// pending/mask state, not four simultaneously retained pending bits.
module agamemnon_ahb_local_int_all_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2,
  input wire hwdata0, input wire hwdata1,
  input wire hwdata2, input wire hwdata3, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [7:0] hrdata,
  output wire [3:0] irq
);
  wire response_zero;
`ifdef SYNTHESIS
  wire write_pending;
  wire select_pending, pending_commit_root, any_write_commit;
  wire write_data_pipe1, low_read0, low_read1;
  wire clear_pulse, set_pulse, pending, mask;
  wire lane0_select, lane1_select;

  // Give every fail-closed response sink one explicit qualified zero source.
  // This is the same source site chosen by the passing cause-16 image, and
  // prevents the generic constant packer from competing for an IRQ source BEL.
  (* keep, BEL = "X14Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0000), .FF_USED(1'b0))
    response_zero_source(.CLK(hclk), .I(4'b0000),
                         .F(response_zero), .Q());

  // Qualified cause-16 transaction and delayed composite-command phase.
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0808), .FF_USED(1'b1))
    write_stage(.CLK(hclk), .I({1'b0, reset_request, hwrite, htrans1}),
                .F(), .Q(write_pending));

  (* keep, BEL = "X17Y12_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    select_pending_stage(.CLK(hclk), .I({2'b00, 1'b1, haddr2}),
                         .F(), .Q(select_pending));
  (* keep, BEL = "X17Y12_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    pending_commit_stage(.CLK(hclk),
                         .I({2'b00, write_pending, select_pending}),
                         .F(), .Q(pending_commit_root));
  assign any_write_commit = pending_commit_root;

  // The qualified low-lane forwarding phase aligns HWDATA with commit.
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFD5D), .FF_USED(1'b0))
    forwarding_mux0(.CLK(hclk),
                    .I({hwdata0, any_write_commit, mask, haddr2}),
                    .F(low_read0), .Q());
  (* keep, BEL = "X14Y10_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b1))
    write_data_capture1(.CLK(hclk), .I({3'b000, hwdata1}),
                        .F(), .Q(write_data_pipe1));
  (* keep, BEL = "X14Y11_SLICE15" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hA808), .FF_USED(1'b0))
    forwarding_mux1(.CLK(hclk),
                    .I({write_data_pipe1, any_write_commit, 1'b0, haddr2}),
                    .F(low_read1), .Q());

  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00D8), .FF_USED(1'b1))
    mask_storage(.CLK(hclk),
                 .I({reset_request, mask, low_read0, pending_commit_root}),
                 .F(), .Q(mask));
  (* keep, BEL = "X15Y11_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    clear_event_stage(.CLK(hclk),
                      .I({2'b00, pending_commit_root, low_read0}),
                      .F(), .Q(clear_pulse));
  (* keep, BEL = "X15Y11_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    set_event_stage(.CLK(hclk),
                    .I({2'b00, pending_commit_root, low_read1}),
                    .F(), .Q(set_pulse));
  (* keep, BEL = "X15Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00DC), .FF_USED(1'b1))
    pending_storage(.CLK(hclk),
                    .I({reset_request, pending, set_pulse, clear_pulse}),
                    .F(), .Q(pending));

  // Store HWDATA[3:2] only when the same delayed command commits. These are
  // the exact direct-data storage footprints qualified by the full byte bank.
  (* keep, BEL = "X14Y11_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hBB88), .FF_USED(1'b1))
    lane0_storage(.CLK(hclk),
                  .I({lane0_select, reset_request,
                      pending_commit_root, hwdata2}),
                  .F(), .Q(lane0_select));
  (* keep, BEL = "X15Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDD88), .FF_USED(1'b1))
    lane1_storage(.CLK(hclk),
                  .I({lane1_select, reset_request,
                      hwdata3, pending_commit_root}),
                  .F(), .Q(lane1_select));

  // Exact source BELs for the four silicon-qualified hard-sink corridors.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0008), .FF_USED(1'b0))
    irq0_gate(.CLK(hclk), .I({lane1_select, lane0_select, pending, mask}),
              .F(irq[0]), .Q());
  (* keep, BEL = "X14Y8_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0080), .FF_USED(1'b0))
    irq1_gate(.CLK(hclk), .I({lane1_select, lane0_select, pending, mask}),
              .F(irq[1]), .Q());
  (* keep, BEL = "X10Y4_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0800), .FF_USED(1'b0))
    irq2_gate(.CLK(hclk), .I({lane1_select, lane0_select, pending, mask}),
              .F(irq[2]), .Q());
  (* keep, BEL = "X14Y4_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8000), .FF_USED(1'b0))
    irq3_gate(.CLK(hclk), .I({lane1_select, lane0_select, pending, mask}),
              .F(irq[3]), .Q());
`else
  reg write_pending = 1'b0;
  reg select_pending = 1'b0;
  reg [1:0] lane_select = 2'b00;
  reg pending = 1'b0;
  reg mask = 1'b0;
  wire commit = write_pending && select_pending;
  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      select_pending <= 1'b0;
      lane_select <= 2'b00;
      pending <= 1'b0;
      mask <= 1'b0;
    end else begin
      write_pending <= htrans1 && hwrite;
      select_pending <= haddr2;
      if (commit) begin
        lane_select <= {hwdata3, hwdata2};
        mask <= hwdata0;
        if (hwdata1)
          pending <= 1'b1;
        else if (hwdata0)
          pending <= 1'b0;
      end
    end
  end
  assign irq[0] = pending && mask && lane_select == 2'd0;
  assign irq[1] = pending && mask && lane_select == 2'd1;
  assign irq[2] = pending && mask && lane_select == 2'd2;
  assign irq[3] = pending && mask && lane_select == 2'd3;
  assign response_zero = 1'b0;
`endif

  assign hrdata = {8{response_zero}};
  assign hreadyout = 1'b1;
  assign hresp = response_zero;
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2;
  wire hwdata0, hwdata1, hwdata2, hwdata3, reset_request;
  wire hreadyout, hresp;
  wire [7:0] hrdata;
  wire [3:0] irq;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata1));
  (* keep *) MCU_DIN mcu_hwdata2(.DIN(hwdata2));
  (* keep *) MCU_DIN mcu_hwdata3(.DIN(hwdata3));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(hreadyout));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(hresp));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(hrdata[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(hrdata[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(hrdata[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(hrdata[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(hrdata[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(hrdata[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(hrdata[7]));
  (* keep *) MCU_LOCAL_INT0 mcu_local_int0(.DOUT(irq[0]));
  (* keep *) MCU_LOCAL_INT1 mcu_local_int1(.DOUT(irq[1]));
  (* keep *) MCU_LOCAL_INT2 mcu_local_int2(.DOUT(irq[2]));
  (* keep *) MCU_LOCAL_INT3 mcu_local_int3(.DOUT(irq[3]));

  agamemnon_ahb_local_int_all_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2),
    .hwdata0(hwdata0), .hwdata1(hwdata1),
    .hwdata2(hwdata2), .hwdata3(hwdata3), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata), .irq(irq));
endmodule
