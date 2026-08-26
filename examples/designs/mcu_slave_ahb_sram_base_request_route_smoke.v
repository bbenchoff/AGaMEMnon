// Hardware-free strict request-side route vehicle for the MCU SRAM base.
// All 11 request controls use the retained registered-source composition.
// HADDR[29] shares the HSEL register/net, HADDR[2] has its independent exact
// register. HADDR[0]/HADDR[1] branch from the exact HSIZE[0]/HSIZE[2]
// routes at their retained shared backbone wires; the other 60 HADDR/HWDATA
// lanes remain on the safe-low tree.
// This is not an AHB transaction generator and makes no silicon claim.
module top;
  wire hclk;
  wire [10:0] control;
  wire haddr2_dynamic;
  (* keep *) wire request_low_omux0;
  (* keep *) wire request_low_omux2;

  MCU_BUS_CLOCK clock_source(.CLK(hclk));

  (* keep, BEL="X14Y7_SLICE14" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_hsel_haddr29(
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

  (* keep, BEL="X18Y9_SLICE15" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) source_haddr2(
    .CLK(hclk), .I({3'b000, haddr2_dynamic}), .F(), .Q(haddr2_dynamic));

  (* keep, BEL="X14Y12_DUAL_SLICE0" *)
  AGRV2K_DUAL_LUT_CONST #(.VALUE(1'b0)) request_low_source(
    .F0(request_low_omux0), .F2(request_low_omux2));

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

  (* keep *) MCU_DOUT haddr0(.DOUT(control[4]));
  (* keep *) MCU_DOUT haddr1(.DOUT(control[6]));
  (* keep *) MCU_DOUT haddr2(.DOUT(haddr2_dynamic));
  (* keep *) MCU_DOUT haddr3(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr4(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr5(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr6(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr7(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr8(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr9(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr10(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr11(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr12(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr13(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr14(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr15(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr16(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr17(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr18(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT haddr19(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr20(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr21(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr22(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr23(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr24(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr25(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr26(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr27(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr28(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr29(.DOUT(control[0]));
  (* keep *) MCU_DOUT haddr30(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr31(.DOUT(request_low_omux0));

  (* keep *) MCU_DOUT hwdata0(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata1(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata2(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata3(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata4(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata5(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata6(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata7(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata8(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata9(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata10(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata11(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata12(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata13(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata14(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata15(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata16(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata17(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata18(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata19(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata20(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata21(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata22(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata23(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata24(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata25(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata26(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata27(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT hwdata28(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata29(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata30(.DOUT(request_low_omux0));
  (* keep *) MCU_DOUT hwdata31(.DOUT(request_low_omux0));
endmodule
