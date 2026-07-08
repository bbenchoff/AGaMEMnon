// techmap: $__ALTA_BRAM9K_ (from memory_libmap / ag32_brams.txt) -> the ALTA_BRAM9K primitive.
// CRITICAL x18 addressing (silicon-proven): the 9-bit word index goes in AddressA[12:4]; the x18
// sub-select AddressA[3:0] must be 4'b1111 (vendor convention). Putting the address in AddressA[8:0]
// reads word 0 always. Single shared port: WeA=write-enable, ReA=1 (always read out DataOutA).
module \$__ALTA_BRAM9K_ (PORT_A_CLK, PORT_A_CLK_EN, PORT_A_ADDR, PORT_A_WR_DATA, PORT_A_WR_EN, PORT_A_RD_DATA);
	parameter INIT = 0;
	parameter PORT_A_WIDTH = 18;
	parameter PORT_A_CLK_POL = 1;
	parameter PORT_A_WR_EN_WIDTH = 1;
	parameter PORT_A_CLK_EN_POL = 1;

	input PORT_A_CLK, PORT_A_CLK_EN;
	input [8:0] PORT_A_ADDR;
	input [PORT_A_WIDTH-1:0] PORT_A_WR_DATA;
	input [PORT_A_WR_EN_WIDTH-1:0] PORT_A_WR_EN;
	output [PORT_A_WIDTH-1:0] PORT_A_RD_DATA;

	wire [17:0] dout;
	wire [17:0] din = {{(18-PORT_A_WIDTH){1'b0}}, PORT_A_WR_DATA};
	assign PORT_A_RD_DATA = dout[PORT_A_WIDTH-1:0];

	ALTA_BRAM9K #(.INIT_VAL(INIT), .PORTA_WIDTH(5'b00000), .CLKMODE(2'b00)) _TECHMAP_REPLACE_ (
		.AddressA({PORT_A_ADDR, 4'b1111}),      // word index -> AddressA[12:4]; x18 sub-select = 1111
		.DataInA(din),
		.DataOutA(dout),
		.WeA(|PORT_A_WR_EN),                      // write when any write-enable bit set
		.ReA(1'b1),                               // always read
		.ByteEnA(2'b11),
		.Clk0(PORT_A_CLK), .Clk1(PORT_A_CLK), .ClkEn0(PORT_A_CLK_EN)
	);
endmodule
