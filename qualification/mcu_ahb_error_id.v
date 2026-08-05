// Deterministic External-AHB error-response qualification endpoint.
// Single aligned word transfers at offset 0 return ID 0x4d/OKAY; offset 4
// returns ERROR. Other widths, bursts, and addresses are outside this oracle.
module agamemnon_ahb_error_id_core (
  input wire hclk, input wire reset_request,
  input wire htrans1, input wire haddr2,
  output wire hreadyout, output wire hresp, output wire [7:0] hrdata
);
`ifdef SYNTHESIS
  wire error_f, phase1, phase2, hresp_f, ready_f;

  // Exact paired MCU consumer footprint: I0=HADDR2, I1=HTRANS1.
  // 8888 asserts ERROR only for an active offset-four transfer.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    error_decode(.CLK(hclk), .I({2'b00, htrans1, haddr2}),
                 .F(error_f), .Q());

  // First ERROR cycle: HRESP high and HREADYOUT low. This is the exact
  // silicon-qualified slice1-token/slice6-ready loop from the controlled-wait
  // image, with address-qualified error_f replacing the unconditional token.
  (* keep, BEL = "X14Y12_SLICE1" *)
  // 0088 = !reset && ready_f && error_f. Gating acceptance with ready
  // clears the token during the stalled cycle and avoids reacceptance.
  GENERIC_SLICE #(.K(4), .INIT(16'h0088), .FF_USED(1'b1))
    error_phase1(.CLK(hclk),
                 .I({reset_request, 1'b0, ready_f, error_f}),
                 .F(), .Q(phase1));

  // Second ERROR cycle: HRESP stays high while HREADYOUT returns high.
  (* keep, BEL = "X14Y11_SLICE4", agamemnon_direct_d_feedback = "1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h2222), .FF_USED(1'b1))
    error_phase2(.CLK(hclk), .I({2'b00, reset_request, phase1}),
                 .F(), .Q(phase2));

  // FCFC = phase1 || phase2. Slice5/I2 is the characterized same-tile
  // destination for the slice4 registered Q; slice5/I1 receives phase1.
  // OMUX15 then drives HRESP through an ordinary strict exit corridor.
  (* keep, BEL = "X14Y11_SLICE5", agamemnon_direct_d_feedback = "1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFCFC), .FF_USED(1'b0))
    response_error(.CLK(hclk), .I({1'b0, phase2, phase1, 1'b0}),
                   .F(hresp_f), .Q());

  (* keep, BEL = "X14Y11_SLICE6" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hDDDD), .FF_USED(1'b0))
    response_ready(.CLK(hclk),
                   .I({2'b00, reset_request, phase1}),
                   .F(ready_f), .Q());
`else
  wire error_f = htrans1 && haddr2;
  reg phase1 = 1'b0;
  reg phase2 = 1'b0;
  wire ready_f = reset_request || !phase1;
  wire hresp_f = phase1 || phase2;
  always @(posedge hclk) begin
    if (reset_request) begin
      phase1 <= 1'b0;
      phase2 <= 1'b0;
    end else begin
      phase1 <= ready_f && error_f;
      phase2 <= phase1;
    end
  end
`endif

  assign hreadyout = ready_f;
  assign hresp = hresp_f;
  // Bit1 is a causal witness for the active ERROR phase.  Offset zero stays
  // 0x4d; a completed error transfer presents 0x4f even if the MCU ignores
  // HRESP, separating response consumption from decoder/state activation.
  assign hrdata = hresp_f ? 8'h4f : 8'h4d;
endmodule

module top;
  wire hclk, reset_request, htrans1, haddr2;
  wire hreadyout, hresp;
  wire [7:0] hrdata;

  agamemnon_ahb_error_id_core core_i(
    .hclk(hclk), .reset_request(reset_request),
    .htrans1(htrans1), .haddr2(haddr2),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata));

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep, BEL = "X10Y5_MCU0" *) MCU mcu_reset_control(.DIN(reset_request));
  (* keep *) MCU_DIN mcu_htrans1(.DIN(htrans1));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
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
