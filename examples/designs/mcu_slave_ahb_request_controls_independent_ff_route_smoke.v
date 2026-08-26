// Exact eleven-source fabric-master request-control route witness.
//
// This is a routing vehicle, not an AHB transaction generator. Each boundary
// sink is driven by the Q output of a separate toggling slice at the one
// retained simultaneous source placement. Arbitrary source placements and
// partial dynamic control groups remain fail-closed.
module mcu_slave_ahb_request_controls_independent_ff_route_smoke;
  wire hclk;
  wire [10:0] control;

  MCU_BUS_CLOCK clock_source(.CLK(hclk));

  (* keep, BEL="X14Y7_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hsel(
    .CLK(hclk), .I({3'b000, control[0]}), .F(), .Q(control[0]));
  (* keep, BEL="X14Y10_SLICE9" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hready(
    .CLK(hclk), .I({3'b000, control[1]}), .F(), .Q(control[1]));
  (* keep, BEL="X14Y7_SLICE11" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_htrans0(
    .CLK(hclk), .I({3'b000, control[2]}), .F(), .Q(control[2]));
  (* keep, BEL="X16Y7_SLICE12" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_htrans1(
    .CLK(hclk), .I({3'b000, control[3]}), .F(), .Q(control[3]));
  (* keep, BEL="X16Y10_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hsize0(
    .CLK(hclk), .I({3'b000, control[4]}), .F(), .Q(control[4]));
  (* keep, BEL="X17Y8_SLICE0" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hsize1(
    .CLK(hclk), .I({3'b000, control[5]}), .F(), .Q(control[5]));
  (* keep, BEL="X14Y10_SLICE10" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hsize2(
    .CLK(hclk), .I({3'b000, control[6]}), .F(), .Q(control[6]));
  (* keep, BEL="X14Y7_SLICE12" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hburst0(
    .CLK(hclk), .I({3'b000, control[7]}), .F(), .Q(control[7]));
  (* keep, BEL="X14Y10_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hburst1(
    .CLK(hclk), .I({3'b000, control[8]}), .F(), .Q(control[8]));
  (* keep, BEL="X17Y8_SLICE2" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hburst2(
    .CLK(hclk), .I({3'b000, control[9]}), .F(), .Q(control[9]));
  (* keep, BEL="X17Y8_SLICE12" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hwrite(
    .CLK(hclk), .I({3'b000, control[10]}), .F(), .Q(control[10]));

  (* keep *) MCU_SLAVE_AHB_HSEL hsel(.DOUT(control[0]));
  (* keep *) MCU_SLAVE_AHB_HREADY hready(.DOUT(control[1]));
  (* keep *) MCU_SLAVE_AHB_HTRANS0 htrans0(.DOUT(control[2]));
  (* keep *) MCU_SLAVE_AHB_HTRANS1 htrans1(.DOUT(control[3]));
  (* keep *) MCU_SLAVE_AHB_HSIZE0 hsize0(.DOUT(control[4]));
  (* keep *) MCU_SLAVE_AHB_HSIZE1 hsize1(.DOUT(control[5]));
  (* keep *) MCU_SLAVE_AHB_HSIZE2 hsize2(.DOUT(control[6]));
  (* keep *) MCU_SLAVE_AHB_HBURST0 hburst0(.DOUT(control[7]));
  (* keep *) MCU_SLAVE_AHB_HBURST1 hburst1(.DOUT(control[8]));
  (* keep *) MCU_SLAVE_AHB_HBURST2 hburst2(.DOUT(control[9]));
  (* keep *) MCU_SLAVE_AHB_HWRITE hwrite(.DOUT(control[10]));
endmodule
