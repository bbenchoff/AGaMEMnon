// Diagnostic-only control for the three offset-8 read gates used by the
// standalone counter register.  Constant-one data inputs isolate HADDR3
// ingress/fanout and HADDR2 gating from the counter-to-read routes.
module top;
  wire hclk, haddr2, haddr3, haddr3_leaf, select8;
  wire [2:0] hrdata;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr3));

  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    haddr3_ingress(.CLK(hclk), .I({haddr3, 3'b000}),
                   .F(haddr3_leaf), .Q());

  (* keep, BEL = "X17Y12_SLICE0", AGRV2K_DISTRIBUTION_ROOT = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h4444), .FF_USED(1'b1))
    select8_stage(.CLK(hclk), .I({2'b00, haddr3_leaf, haddr2}),
                  .F(), .Q(select8));
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    read0(.CLK(hclk), .I({2'b00, select8, 1'b1}),
          .F(hrdata[0]), .Q());
  (* keep, BEL = "X14Y11_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    read1(.CLK(hclk), .I({2'b00, select8, 1'b1}),
          .F(hrdata[1]), .Q());
  (* keep, BEL = "X14Y11_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    read2(.CLK(hclk), .I({2'b00, select8, 1'b1}),
          .F(hrdata[2]), .Q());

  (* keep *) MCU_AHB_HREADYOUT mcu_hreadyout(.DOUT(1'b1));
  (* keep *) MCU_AHB_HRESP mcu_hresp(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h0(.DOUT(hrdata[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(hrdata[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(hrdata[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(1'b0));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(1'b0));
endmodule
