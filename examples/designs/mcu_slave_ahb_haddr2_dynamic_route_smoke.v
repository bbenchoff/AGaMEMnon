// Hardware-free strict route vehicle for the first independent request-payload lane.
// HADDR[2] uses one retained registered source and exact five-edge route; every
// other HADDR/HWDATA lane stays on the previously qualified safe-low tree.
// This is not an AHB transaction generator and makes no silicon-behavior claim.
module top;
  wire hclk;
  wire haddr2_dynamic;
  (* keep *) wire request_low_omux0;
  (* keep *) wire request_low_omux2;

  MCU_BUS_CLOCK clock_source(.CLK(hclk));
  (* keep, BEL="X18Y9_SLICE15" *)
  GENERIC_SLICE #(.INIT(16'h5555), .FF_USED(1)) haddr2_source(
    .CLK(hclk), .I({3'b000, haddr2_dynamic}), .F(), .Q(haddr2_dynamic));

  (* keep, BEL="X14Y12_DUAL_SLICE0" *)
  AGRV2K_DUAL_LUT_CONST #(.VALUE(1'b0)) request_low_source(
    .F0(request_low_omux0), .F2(request_low_omux2));

  (* keep *) MCU_DOUT haddr0(.DOUT(request_low_omux2));
  (* keep *) MCU_DOUT haddr1(.DOUT(request_low_omux0));
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
  (* keep *) MCU_DOUT haddr29(.DOUT(request_low_omux2));
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
