// LUT and DFF are combined to a GENERIC_SLICE

module LUT #(
	parameter K = 4,
	parameter [2**K-1:0] INIT = 0
) (
	input [K-1:0] I,
	output Q
);
	wire [K-1:0] I_pd;

	genvar ii;
	generate
		for (ii = 0; ii < K; ii = ii + 1'b1)
			assign I_pd[ii] = (I[ii] === 1'bz) ? 1'b0 : I[ii];
	endgenerate

	assign Q = INIT[I_pd];
endmodule

module DFF (
	input CLK, D,
	output reg Q
);
	initial Q = 1'b0;
	always @(posedge CLK)
		Q <= D;
endmodule

module GENERIC_SLICE #(
	parameter K = 4,
	parameter [2**K-1:0] INIT = 0,
	parameter FF_USED = 1'b0
) (
	input CLK,
	input [K-1:0] I,
	output F,
	output Q
);
	wire f_wire;
	
	LUT #(.K(K), .INIT(INIT)) lut_i(.I(I), .Q(f_wire));

	DFF dff_i(.CLK(CLK), .D(f_wire), .Q(Q));

	assign F = f_wire;
endmodule

// The AG32 MCU hard block as a nextpnr placeable cell. Blackbox: yosys must NOT synthesize into
// it; it maps 1:1 onto the `MCU` bel that arch.py adds at UFMTILE(0,5). DIN = a GPIO output bit
// the MCU drives into the fabric; DOUT = a GPIO input bit the fabric drives back to the MCU
// (mirrors the vendor loopback: gpio4_io_out_data[1] / gpio4_io_in[2]).
(* blackbox *)
module MCU (
	output DIN,
	input  DOUT
);
endmodule

// MCU->fabric bus INPUT (e.g. an AHB signal hwdata/hwrite/htrans the MCU drives into the fabric).
(* blackbox *)
module MCU_DIN (
	output DIN
);
endmodule

// fabric->MCU OUTPUT (e.g. GPIO observability / hrdata readback the fabric drives to the MCU).
(* blackbox *)
module MCU_DOUT (
	input DOUT
);
endmodule

module GENERIC_IOB #(
	parameter INPUT_USED = 1'b0,
	parameter OUTPUT_USED = 1'b0,
	parameter ENABLE_USED = 1'b0
) (
	inout PAD,
	input I, EN,
	output O
);
	generate if (OUTPUT_USED && ENABLE_USED)
		assign PAD = EN ? I : 1'bz;
	else if (OUTPUT_USED)
		assign PAD = I;
	endgenerate

	generate if (INPUT_USED)
		assign O = PAD;
	endgenerate
endmodule

// AGRV2K dual-port 9-Kbit block RAM, the map target for inferred memories (memory_libmap ->
// ag32_brams.txt -> ag32_brams_map.v). x18 = 512 words x 18 bits; INIT_VAL word i = INIT_VAL[i*18 +: 18].
// Each port has its own address/data/control/clock pins. bitgen (bram_emit) + the arch bel carry the
// placed primitive; unsupported reset/stall modes remain deliberately absent from this open interface.
(* blackbox *)
module ALTA_BRAM9K #(parameter [9215:0] INIT_VAL = 0,
                     parameter [4:0] PORTA_WIDTH = 0, parameter [4:0] PORTB_WIDTH = 0,
                     parameter [1:0] CLKMODE = 0,
                     parameter PORTA_CLKIN_EN = 0, parameter PORTA_CLKOUT_EN = 0,
                     parameter PORTA_RSTIN_EN = 0, parameter PORTA_RSTOUT_EN = 0,
                     parameter PORTB_CLKIN_EN = 0, parameter PORTB_CLKOUT_EN = 0,
                     parameter PORTB_RSTIN_EN = 0, parameter PORTB_RSTOUT_EN = 0) (
	input [12:0] AddressA, input [17:0] DataInA, output [17:0] DataOutA,
	input WeA, input ReA, input [1:0] ByteEnA,
	input [12:0] AddressB, input [17:0] DataInB, output [17:0] DataOutB,
	input WeB, input ReB, input [1:0] ByteEnB,
	input Clk0, input Clk1, input ClkEn0, input ClkEn1);
endmodule
