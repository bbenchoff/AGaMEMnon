`timescale 1ns/1ps

// Behavioral models for standalone MCU/fabric-interface simulations. These
// modules are not used by synthesis; agamemnon/synth/prims.v remains the
// black-box contract consumed by Yosys.
module MCU_BUS_CLOCK #(
  parameter integer HALF_PERIOD_NS = 5
) (output reg CLK);
  initial begin
    CLK = 1'b0;
    forever #HALF_PERIOD_NS CLK = ~CLK;
  end
endmodule

module MCU_SYS_CLOCK #(
  parameter integer HALF_PERIOD_NS = 5
) (output reg CLK);
  initial begin
    CLK = 1'b0;
    forever #HALF_PERIOD_NS CLK = ~CLK;
  end
endmodule

module MCU_RESETN #(
  parameter integer RELEASE_NS = 22
) (output reg RESETN);
  initial begin
    RESETN = 1'b0;
    #RELEASE_NS RESETN = 1'b1;
  end
endmodule

module MCU_DOUT(input DOUT);
endmodule

module MCU_DIN(output reg DIN);
  initial DIN = 1'b0;
endmodule

// Fabric-master boundary models. Request ports are sinks; the standalone
// default response is an always-ready, error-free, zero-data slave so the
// complete AG32 wrapper can be protocol-simulated without hard-block models.
module MCU_SLAVE_AHB_HSEL(input DOUT); endmodule
module MCU_SLAVE_AHB_HREADY(input DOUT); endmodule
module MCU_SLAVE_AHB_HTRANS0(input DOUT); endmodule
module MCU_SLAVE_AHB_HTRANS1(input DOUT); endmodule
module MCU_SLAVE_AHB_HSIZE0(input DOUT); endmodule
module MCU_SLAVE_AHB_HSIZE1(input DOUT); endmodule
module MCU_SLAVE_AHB_HSIZE2(input DOUT); endmodule
module MCU_SLAVE_AHB_HBURST0(input DOUT); endmodule
module MCU_SLAVE_AHB_HBURST1(input DOUT); endmodule
module MCU_SLAVE_AHB_HBURST2(input DOUT); endmodule
module MCU_SLAVE_AHB_HWRITE(input DOUT); endmodule
module MCU_SLAVE_AHB_HREADYOUT(output wire DIN); assign DIN = 1'b1; endmodule
module MCU_SLAVE_AHB_HRESP(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA0(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA1(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA2(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA3(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA4(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA5(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA6(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA7(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA8(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA9(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA10(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA11(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA12(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA13(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA14(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA15(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA16(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA17(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA18(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA19(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA20(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA21(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA22(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA23(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA24(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA25(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA26(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA27(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA28(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA29(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA30(output wire DIN); assign DIN = 1'b0; endmodule
module MCU_SLAVE_AHB_HRDATA31(output wire DIN); assign DIN = 1'b0; endmodule

module MCU_AHB_HREADY(output reg DIN);
  initial DIN = 1'b1;
endmodule
module MCU_AHB_HTRANS0(output reg DIN); initial DIN = 1'b0; endmodule
module MCU_AHB_HSIZE0(output reg DIN);   initial DIN = 1'b0; endmodule
module MCU_AHB_HSIZE1(output reg DIN);   initial DIN = 1'b1; endmodule
module MCU_AHB_HSIZE2(output reg DIN);   initial DIN = 1'b0; endmodule
module MCU_AHB_HBURST0(output reg DIN);  initial DIN = 1'b0; endmodule
module MCU_AHB_HBURST1(output reg DIN);  initial DIN = 1'b0; endmodule
module MCU_AHB_HBURST2(output reg DIN);  initial DIN = 1'b0; endmodule
module MCU_AHB_HREADYOUT(input DOUT); endmodule
module MCU_AHB_HRESP(input DOUT); endmodule
// Behavioral LUT model used when an endpoint deliberately preserves a
// lane-local combinational source for physical routing.
module LUT #(
  parameter integer K = 4,
  parameter [(1 << K)-1:0] INIT = 0
) (
  input wire [K-1:0] I,
  output wire Q
);
  assign Q = INIT[I];
endmodule
