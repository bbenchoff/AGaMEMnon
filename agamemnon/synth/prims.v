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

// Guarded physical primitive for the vendor-observed safe-idle high-fanout
// case. Both outputs carry VALUE from one physical slice; F0 is OMUX[3z+0]
// and F2 is the default OMUX[3z+2].
(* blackbox *) module AGRV2K_DUAL_LUT_CONST #(
    parameter VALUE = 1'b0
) (
    output F0,
    output F2
);
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

// The vendor-generated AG32 top aliases bus_clk to the fabric system global
// clock (sys_gck). These two typed names deliberately drive the same source.
(* blackbox *) module MCU_SYS_CLOCK (output CLK); endmodule
(* blackbox *) module MCU_BUS_CLOCK (output CLK); endmodule
(* blackbox *) module MCU_RESETN (output RESETN); endmodule
(* blackbox *) module MCU_STOP (output DIN); endmodule
// One independently recovered GPIO5 boundary unit. These names encode the
// exact hard signal and bit; they do not imply general GPIO-matrix support.
(* blackbox *) module MCU_GPIO5_OUT_DATA1 (output DIN); endmodule
(* blackbox *) module MCU_GPIO5_OUT_EN1 (output DIN); endmodule
(* blackbox *) module MCU_GPIO5_IN2 (input DOUT); endmodule
// Read-only fabric source for the first recovered ADC hard-block result lane.
// This exposes routing only; it does not configure, start, or qualify the ADC.
(* blackbox *) module AGRV2K_ADC0_DB0 (output DB); endmodule
(* blackbox *) module AGRV2K_ADC0_DB1 (output DB); endmodule
(* blackbox *) module AGRV2K_ADC0_EOC (output EOC); endmodule
(* blackbox *) module MCU_LOCAL_INT0 (input DOUT); endmodule
(* blackbox *) module MCU_LOCAL_INT1 (input DOUT); endmodule
(* blackbox *) module MCU_LOCAL_INT2 (input DOUT); endmodule
(* blackbox *) module MCU_LOCAL_INT3 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HREADYOUT (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRESP (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA0 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA1 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA2 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA3 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA4 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA5 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA6 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA7 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA8 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA9 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA10 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA11 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA12 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA13 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA14 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA15 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA16 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA17 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA18 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA19 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA20 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA21 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA22 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA23 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA24 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA25 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA26 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA27 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA28 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA29 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA30 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HRDATA31 (output DIN); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HSEL (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HREADY (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HTRANS0 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HTRANS1 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HSIZE0 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HSIZE1 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HSIZE2 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HBURST0 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HBURST1 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HBURST2 (input DOUT); endmodule
(* blackbox *) module MCU_SLAVE_AHB_HWRITE (input DOUT); endmodule
(* blackbox *) module MCU_DMA_CLR0 (output DIN); endmodule
(* blackbox *) module MCU_DMA_TC0 (output DIN); endmodule
(* blackbox *) module MCU_DMA_CLR1 (output DIN); endmodule
(* blackbox *) module MCU_DMA_CLR2 (output DIN); endmodule
(* blackbox *) module MCU_DMA_CLR3 (output DIN); endmodule
(* blackbox *) module MCU_DMA_TC1 (output DIN); endmodule
(* blackbox *) module MCU_DMA_TC2 (output DIN); endmodule
(* blackbox *) module MCU_DMA_TC3 (output DIN); endmodule
(* blackbox *) module MCU_DMA_BREQ0 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LBREQ0 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_SREQ0 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LSREQ0 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_BREQ1 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_BREQ2 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_BREQ3 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LBREQ1 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LBREQ2 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LBREQ3 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_SREQ1 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_SREQ2 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_SREQ3 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LSREQ1 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LSREQ2 (input DOUT); endmodule
(* blackbox *) module MCU_DMA_LSREQ3 (input DOUT); endmodule

// Typed External AHB control ports. Each cell type has exactly one matching
// physical BEL, so request and response bits cannot be permuted by placement.
(* blackbox *) module MCU_AHB_HREADY   (output DIN); endmodule
(* blackbox *) module MCU_AHB_HTRANS0  (output DIN); endmodule
(* blackbox *) module MCU_AHB_HSIZE0    (output DIN); endmodule
(* blackbox *) module MCU_AHB_HSIZE1    (output DIN); endmodule
(* blackbox *) module MCU_AHB_HSIZE2    (output DIN); endmodule
(* blackbox *) module MCU_AHB_HBURST0   (output DIN); endmodule
(* blackbox *) module MCU_AHB_HBURST1   (output DIN); endmodule
(* blackbox *) module MCU_AHB_HBURST2   (output DIN); endmodule
(* blackbox *) module MCU_AHB_HREADYOUT (input DOUT); endmodule
(* blackbox *) module MCU_AHB_HRESP     (input DOUT); endmodule

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
