// Standalone one-bit W1C status class at offset C.
//
// Qualification uses an internal AHB software-set hook so no package pin is
// required: writing bit1 injects a one-cycle set event, while writing bit0
// clears the latched status.  Set has priority when both are requested.
module agamemnon_ahb_w1c_status1_core (
  input wire hclk, input wire htrans1, input wire hwrite,
  input wire haddr2, input wire haddr3,
  input wire hwdata0, input wire hwdata1,
  output wire [7:0] hrdata
);
`ifdef SYNTHESIS
  wire haddr3_leaf;
  wire write_pending, select_c;
  wire write_c_commit, set_pulse, clear_pulse, status;

  // HADDR3 retains its exact slice0/I3 ingress. The already-qualified paired
  // HTRANS1/HWRITE token is registered at slice1, leaving slice0 available.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    addr3_ingress(.CLK(hclk), .I({haddr3, 3'b000}),
                  .F(haddr3_leaf), .Q());
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    write_stage(.CLK(hclk), .I({2'b00, hwrite, htrans1}),
                .F(), .Q(write_pending));

  // Register the offset-C address select across the AHB phase boundary.
  (* keep, BEL = "X17Y12_SLICE0", AGRV2K_DISTRIBUTION_ROOT = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    select_c_stage(.CLK(hclk), .I({2'b00, haddr3_leaf, haddr2}),
                   .F(), .Q(select_c));
  (* keep, BEL = "X17Y12_SLICE2" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    write_c_decode(.CLK(hclk), .I({2'b00, select_c, write_pending}),
                   .F(write_c_commit), .Q());

  // HWDATA1's exact registered consumer is X14Y10 slice3/I1. It produces a
  // one-cycle event pulse only for a valid offset-C write.
  (* keep, BEL = "X14Y10_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    set_event_stage(.CLK(hclk),
                    .I({2'b00, hwdata1, write_c_commit}),
                    .F(), .Q(set_pulse));

  // HWDATA0 likewise enters through its exact X14Y11 slice5/I1 capture.
  (* keep, BEL = "X14Y11_SLICE5" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b1))
    clear_event_stage(.CLK(hclk),
                      .I({2'b00, hwdata0, write_c_commit}),
                      .F(), .Q(clear_pulse));

  // I2=own Q, I1=set pulse, I0=clear pulse. DCDC implements
  // set | (Q & !clear), so set wins when both event bits are written.
  (* keep, BEL = "X14Y11_SLICE7" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDCDC), .FF_USED(1'b1))
    status_storage(.CLK(hclk),
                   .I({1'b0, status, set_pulse, clear_pulse}),
                   .F(), .Q(status));

  // Return status only for the registered offset-C data phase.
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    status_read(.CLK(hclk), .I({2'b00, select_c, status}),
                .F(hrdata[0]), .Q());
  assign hrdata[7:1] = 7'b0000000;
`else
  reg write_pending = 1'b0;
  reg select_c = 1'b0;
  reg set_pulse = 1'b0;
  reg status = 1'b0;
  wire write_c_commit = write_pending && select_c;
  always @(posedge hclk) begin
    write_pending <= htrans1 && hwrite;
    select_c <= haddr3 && haddr2;
    set_pulse <= write_c_commit && hwdata1;
    if (set_pulse)
      status <= 1'b1;
    else if (write_c_commit && hwdata0)
      status <= 1'b0;
  end
  assign hrdata = select_c ? {7'b0, status} : 8'h00;
`endif
endmodule

module top;
  wire hclk, htrans1, hwrite, haddr2, haddr3, hwdata0, hwdata1;
  wire [7:0] hrdata;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_hwrite(.DIN(hwrite));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr3));
  (* keep *) MCU_DIN mcu_hwdata0(.DIN(hwdata0));
  (* keep *) MCU_DIN mcu_hwdata1(.DIN(hwdata1));
  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(1'b1));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(hrdata[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(hrdata[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(hrdata[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(hrdata[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(hrdata[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(hrdata[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(hrdata[7]));
  agamemnon_ahb_w1c_status1_core core_i(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3),
    .hwdata0(hwdata0), .hwdata1(hwdata1), .hrdata(hrdata));
endmodule
