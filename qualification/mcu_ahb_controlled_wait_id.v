// Controlled-wait External-AHB qualification endpoint.
// Every valid transfer receives exactly one wait; reads return ID byte 0x4d.
module agamemnon_ahb_controlled_wait_id_core (
  input wire hclk, input wire htrans1, input wire reset_request,
  output wire hreadyout, output wire hresp, output wire [7:0] hrdata
);
`ifdef SYNTHESIS
  wire htrans1_leaf;
  wire transfer_pending;
  wire ready_f;
`else
  reg transfer_pending = 1'b0;
  wire ready_f = reset_request || !transfer_pending;
`endif

  assign hreadyout = ready_f;
  assign hresp = 1'b0;
  assign hrdata = 8'h4d;

`ifdef SYNTHESIS
  // Terminate the qualified MCU input consumer at slice0 before the token
  // stage.  The paired slice0/slice1 footprint is the same hard ingress
  // arrangement used by the routed combined-bank wait image.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    htrans_ingress(.CLK(hclk), .I({htrans1, 3'b000}),
                   .F(htrans1_leaf), .Q());

  // 0088 = !reset_request && ready_f && htrans1. Gating acceptance
  // with ready clears the token during the stalled cycle and prevents a held
  // HTRANS from creating a second transfer.
  (* keep, BEL = "X14Y12_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h0088), .FF_USED(1'b1))
    transfer_stage(.CLK(hclk),
                   .I({reset_request, 1'b0, ready_f, htrans1_leaf}),
                   .F(), .Q(transfer_pending));

  // DDDD = reset_request || !transfer_pending. F/OMUX20 drives the
  // exact silicon-qualified dynamic HREADYOUT route.
  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDDDD), .FF_USED(1'b0))
    ready_stage(.CLK(hclk),
                .I({2'b00, reset_request, transfer_pending}),
                .F(ready_f), .Q());
`else
  always @(posedge hclk) begin
    if (reset_request)
      transfer_pending <= 1'b0;
    else
      transfer_pending <= ready_f && htrans1;
  end
`endif
endmodule

module top;
  wire hclk, htrans1, reset_request;
  wire hreadyout, hresp;
  wire [7:0] hrdata;

  agamemnon_ahb_controlled_wait_id_core core_i(
    .hclk(hclk), .htrans1(htrans1), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata));

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
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
endmodule
