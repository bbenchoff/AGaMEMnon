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
