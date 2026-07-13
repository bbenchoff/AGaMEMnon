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
	parameter PORT_A_OPTION_WRITEMODE = "OLD";
	parameter PORT_A_RD_INIT_VALUE = 0;

	input PORT_A_CLK, PORT_A_CLK_EN;
	input [12:0] PORT_A_ADDR;
	input [PORT_A_WIDTH-1:0] PORT_A_WR_DATA;
	input [PORT_A_WR_EN_WIDTH-1:0] PORT_A_WR_EN;
	output [PORT_A_WIDTH-1:0] PORT_A_RD_DATA;

	wire [17:0] dout;
	wire [17:0] din = {{(18-PORT_A_WIDTH){1'b0}}, PORT_A_WR_DATA};
	assign PORT_A_RD_DATA = dout[PORT_A_WIDTH-1:0];

	// DWSEL is a thermometer code: 0=x18, 01000=x9, then progressively
	// narrower modes.  The x18 oracle uses the nine word-address bits in
	// AddressA[12:4] with the low nibble at 1111; narrow modes use the native
	// low-address representation seen in the vendor SERV register-file cell.
	localparam [4:0] DWSEL = PORT_A_WIDTH >= 18 ? 5'b00000 :
	                         PORT_A_WIDTH >= 9  ? 5'b01000 :
	                         PORT_A_WIDTH >= 4  ? 5'b01100 :
	                         PORT_A_WIDTH >= 2  ? 5'b01110 : 5'b01111;
	wire [12:0] phys_addr = PORT_A_WIDTH >= 18 ? {PORT_A_ADDR[8:0], 4'b1111} : PORT_A_ADDR;

	ALTA_BRAM9K #(.INIT_VAL(INIT), .PORTA_WIDTH(DWSEL), .CLKMODE(2'b00)) _TECHMAP_REPLACE_ (
		.AddressA(phys_addr),
		.DataInA(din),
		.DataOutA(dout),
		.WeA(|PORT_A_WR_EN),                      // write when any write-enable bit set
		.ReA(1'b1),                               // always read
		.ByteEnA(2'b11),
		.Clk0(PORT_A_CLK), .Clk1(PORT_A_CLK), .ClkEn0(PORT_A_CLK_EN)
	);
endmodule
