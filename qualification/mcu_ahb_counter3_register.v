// Standalone lower-three-bit read-only counter register at offset 8.
// The upper five return bits are hard zero. This qualifies the counter class
// independently of the still-open full ID/scratch/counter/W1C integration.
module agamemnon_ahb_counter3_register_core (
  input wire hclk, input wire haddr2, input wire haddr3,
  output wire [7:0] hrdata
);
`ifdef SYNTHESIS
  wire haddr3_leaf, select8;
  wire q0, q1, q2;
  wire f0, f1, f2;
  wire [2:0] counter = {f2, f1, f0};

  // Exact silicon-qualified HADDR3 ingress: X14Y12 slice0/I3.
  (* keep, BEL = "X14Y12_SLICE0" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hFF00), .FF_USED(1'b0))
    haddr3_ingress(.CLK(hclk), .I({haddr3, 3'b000}),
                   .F(haddr3_leaf), .Q());

  // Capture the address-phase offset select at the AHB data-phase boundary.
  // X17Y12 slice0 is the qualified distribution-root stage.
  (* keep, BEL = "X17Y12_SLICE0", AGRV2K_DISTRIBUTION_ROOT = 1 *)
  GENERIC_SLICE #(.K(4), .INIT(16'h4444), .FF_USED(1'b1))
    select8_stage(.CLK(hclk), .I({2'b00, haddr3_leaf, haddr2}),
                  .F(), .Q(select8));

  // Exact three-site direct-D counter already qualified over all eight states.
  (* keep, BEL = "X14Y11_SLICE4", agamemnon_direct_d_feedback = "1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h00FF), .FF_USED(1'b1))
    counter0(.CLK(hclk), .I({q0, 3'b000}), .F(f0), .Q(q0));
  (* keep, BEL = "X14Y11_SLICE6", agamemnon_direct_d_feedback = "1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hAA55), .FF_USED(1'b1))
    counter1(.CLK(hclk), .I({q1, 2'b00, f0}), .F(f1), .Q(q1));
  (* keep, BEL = "X14Y11_SLICE7", agamemnon_direct_d_feedback = "1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'hEE11), .FF_USED(1'b1))
    counter2(.CLK(hclk), .I({q2, 1'b0, f1, f0}), .F(f2), .Q(q2));

  // 8888 implements the registered offset-8 select AND counter_bit.
  (* keep, BEL = "X14Y11_SLICE14" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    read0(.CLK(hclk), .I({2'b00, select8, counter[0]}), .F(hrdata[0]), .Q());
  (* keep, BEL = "X14Y11_SLICE3" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    read1(.CLK(hclk), .I({2'b00, select8, counter[1]}), .F(hrdata[1]), .Q());
  (* keep, BEL = "X14Y11_SLICE1" *)
  GENERIC_SLICE #(.K(4), .INIT(16'h8888), .FF_USED(1'b0))
    read2(.CLK(hclk), .I({2'b00, select8, counter[2]}), .F(hrdata[2]), .Q());
  assign hrdata[7:3] = 5'b00000;
`else
  reg [2:0] counter = 3'b000;
  always @(posedge hclk)
    counter <= counter + 1'b1;
  assign hrdata = (haddr3 && !haddr2) ? {5'b0, counter} : 8'h00;
`endif
endmodule

module top;
  wire hclk, haddr2, haddr3;
  wire [7:0] hrdata;
  wire hreadyout = 1'b1;
  wire hresp = 1'b0;
  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(hclk));
  (* keep *) MCU_DIN mcu_haddr2(.DIN(haddr2));
  (* keep *) MCU_DIN mcu_haddr3(.DIN(haddr3));
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
  agamemnon_ahb_counter3_register_core core_i(
    .hclk(hclk), .haddr2(haddr2), .haddr3(haddr3), .hrdata(hrdata));
endmodule
