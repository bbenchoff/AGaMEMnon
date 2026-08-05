// AHB-backed local_int[1] pending/mask/ack/re-arm controller.
//
// Offset 4 writes the one-bit mask (bit0). Offset C writes the pending W1C
// command (bit1=set qualification hook, bit0=ack). Reads return zero; no state
// readback is claimed. GPIO4.1 synchronously resets both bits. The state cells are
// the silicon-qualified subset of the combined register bank; the final AND
// occupies the exact source BEL of the qualified cause-17 corridor.
module agamemnon_ahb_local_int1_bank_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire haddr3,
  input wire hwdata0, input wire hwdata1, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [7:0] hrdata,
  output wire irq_pending, output wire irq_mask, output wire irq1
);
`ifdef SYNTHESIS
  wire haddr3_leaf, write_pending;
  wire mask_commit_root, select_pending, pending_commit_root;
  wire any_write_commit, mask_commit;
  wire write_data_pipe1, low_read0, low_read1;
  wire clear_pulse, set_pulse, pending, mask;

  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    addr3_ingress(.CLK(hclk), .I({haddr3, 3'b000}),
                  .F(haddr3_leaf), .Q());
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0808), .FF_USED(1'b1))
    write_stage(.CLK(hclk), .I({1'b0, reset_request, hwrite, htrans1}),
                .F(), .Q(write_pending));

  (* keep, BEL = "X17Y12_SLICE0", AGRV2K_DISTRIBUTION_ROOT = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2020), .FF_USED(1'b1))
    mask_commit_stage(.CLK(hclk),
                      .I({1'b0, write_pending, haddr3_leaf, haddr2}),
                      .F(), .Q(mask_commit_root));
  (* keep, BEL = "X17Y12_SLICE4" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    select_pending_stage(.CLK(hclk),
                         .I({2'b00, haddr3_leaf, haddr2}),
                         .F(), .Q(select_pending));
  (* keep, BEL = "X17Y12_SLICE8" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    pending_commit_stage(.CLK(hclk),
                         .I({2'b00, write_pending, select_pending}),
                         .F(), .Q(pending_commit_root));
  (* keep, BEL = "X17Y12_SLICE10" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hEEEE), .FF_USED(1'b0))
    any_commit_decode(.CLK(hclk),
                      .I({2'b00, pending_commit_root, mask_commit_root}),
                      .F(any_write_commit), .Q());

  (* keep, BEL = "X14Y7_SLICE3", AGRV2K_ROUTE_THROUGH = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    mask_commit_route(.CLK(hclk), .I({mask_commit_root, 3'b000}),
                      .F(mask_commit), .Q());

  // Exact lane-zero/lane-one posted forwarding paths from the combined bank.
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
                 .I({reset_request, mask, hwdata0, mask_commit}),
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

  assign hrdata[0] = 1'b0;
`else
  reg write_pending = 1'b0;
  reg select_mask = 1'b0;
  reg select_pending = 1'b0;
  reg mask = 1'b0;
  reg pending = 1'b0;
  wire mask_commit = write_pending && select_mask;
  wire pending_commit = write_pending && select_pending;
  always @(posedge hclk) begin
    if (reset_request) begin
      write_pending <= 1'b0;
      select_mask <= 1'b0;
      select_pending <= 1'b0;
      mask <= 1'b0;
      pending <= 1'b0;
    end else begin
      if (mask_commit)
        mask <= hwdata0;
      if (pending_commit && hwdata1)
        pending <= 1'b1;
      else if (pending_commit && hwdata0)
        pending <= 1'b0;
      write_pending <= htrans1 && hwrite;
      select_mask <= !haddr3 && haddr2;
      select_pending <= haddr3 && haddr2;
    end
  end
  assign hrdata[0] = 1'b0;
`endif
  assign hrdata[7:1] = 7'b0000000;
  assign hreadyout = 1'b1;
  assign hresp = 1'b0;
  assign irq_pending = pending;
  assign irq_mask = mask;

`ifdef SYNTHESIS
`ifdef AGAMEMNON_LOCAL_INT2
  (* keep, BEL = "X10Y4_SLICE0" *)
`else
  (* keep, BEL = "X14Y8_SLICE0" *)
`endif
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    irq1_gate(.CLK(hclk), .I({2'b00, pending, mask}), .F(irq1), .Q());
`else
  assign irq1 = pending && mask;
`endif
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2, haddr3;
  wire hwdata0, hwdata1, reset_request;
  wire hreadyout, hresp, irq_pending, irq_mask, irq1;
  wire [7:0] hrdata;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr3));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata1));
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
`ifdef AGAMEMNON_LOCAL_INT2
  (* keep *) MCU_LOCAL_INT2 mcu_local_int2(.DOUT(irq1));
`else
  (* keep *) MCU_LOCAL_INT1 mcu_local_int1(.DOUT(irq1));
`endif
  agamemnon_ahb_local_int1_bank_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3),
    .hwdata0(hwdata0), .hwdata1(hwdata1), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata),
    .irq_pending(irq_pending), .irq_mask(irq_mask), .irq1(irq1));
endmodule
