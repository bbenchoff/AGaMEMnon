// techmap: $__ALTA_BRAM9K_ (from memory_libmap / ag32_brams.txt) -> the dual-port ALTA_BRAM9K primitive.
// CRITICAL x18 addressing (silicon-proven): the 9-bit word index goes in AddressA[12:4]; the x18
// sub-select AddressA[3:0] must be 4'b1111 (vendor convention). Putting the address in AddressA[8:0]
// reads word 0 always. Port A and Port B remain independent; the current SERV register file uses
// synchronous reads on both ports and writes through Port A.
module \$__ALTA_BRAM9K_ (PORT_A_CLK, PORT_A_CLK_EN, PORT_A_ADDR, PORT_A_WR_DATA, PORT_A_WR_EN, PORT_A_RD_DATA,
				 PORT_B_CLK, PORT_B_CLK_EN, PORT_B_ADDR, PORT_B_WR_DATA, PORT_B_WR_EN, PORT_B_RD_DATA);
	parameter INIT = 0;
	parameter PORT_A_WIDTH = 18;
	parameter PORT_A_CLK_POL = 1;
	parameter PORT_A_WR_EN_WIDTH = 1;
	parameter PORT_A_CLK_EN_POL = 1;
	parameter PORT_A_OPTION_WRITEMODE = "OLD";
	parameter PORT_A_RD_INIT_VALUE = 0;
	parameter PORT_B_WIDTH = 18;
	parameter PORT_B_CLK_POL = 1;
	parameter PORT_B_WR_EN_WIDTH = 1;
	parameter PORT_B_CLK_EN_POL = 1;
	parameter PORT_B_OPTION_WRITEMODE = "OLD";
	parameter PORT_B_RD_INIT_VALUE = 0;

	input PORT_A_CLK, PORT_A_CLK_EN;
	input [12:0] PORT_A_ADDR;
	input [PORT_A_WIDTH-1:0] PORT_A_WR_DATA;
	input [PORT_A_WR_EN_WIDTH-1:0] PORT_A_WR_EN;
	output [PORT_A_WIDTH-1:0] PORT_A_RD_DATA;
	input PORT_B_CLK, PORT_B_CLK_EN;
	input [12:0] PORT_B_ADDR;
	input [PORT_B_WIDTH-1:0] PORT_B_WR_DATA;
	input [PORT_B_WR_EN_WIDTH-1:0] PORT_B_WR_EN;
	output [PORT_B_WIDTH-1:0] PORT_B_RD_DATA;

	wire [17:0] dout_a, dout_b;
	// alta_bram9k exposes eighteen physical lanes.  Narrow logical words are
	// repeated into those lanes on write and selected from non-zero-offset
	// lanes on read (matching alta_ram9k's vendor wrapper), rather than simply
	// occupying DataIn/DataOut[width-1:0].
	wire [17:0] din_a = PORT_A_WIDTH >= 18 ? PORT_A_WR_DATA[17:0] :
	                      PORT_A_WIDTH >= 9  ? {2{PORT_A_WR_DATA[8:0]}} :
	                      PORT_A_WIDTH >= 4  ? {2{1'b1, {2{PORT_A_WR_DATA[3:0]}}}} :
	                      PORT_A_WIDTH >= 2  ? {2{1'b1, {4{PORT_A_WR_DATA[1:0]}}}} :
	                                           {2{1'b1, {8{PORT_A_WR_DATA[0]}}}};
	wire [17:0] din_b = PORT_B_WIDTH >= 18 ? PORT_B_WR_DATA[17:0] :
	                      PORT_B_WIDTH >= 9  ? {2{PORT_B_WR_DATA[8:0]}} :
	                      PORT_B_WIDTH >= 4  ? {2{1'b1, {2{PORT_B_WR_DATA[3:0]}}}} :
	                      PORT_B_WIDTH >= 2  ? {2{1'b1, {4{PORT_B_WR_DATA[1:0]}}}} :
	                                           {2{1'b1, {8{PORT_B_WR_DATA[0]}}}};
	assign PORT_A_RD_DATA = PORT_A_WIDTH >= 18 ? dout_a[17:0] :
	                            PORT_A_WIDTH >= 9  ? {dout_a[7], dout_a[16:9]} :
	                            PORT_A_WIDTH >= 4  ? dout_a[6:3] :
	                            PORT_A_WIDTH >= 2  ? dout_a[2:1] : dout_a[0];
	assign PORT_B_RD_DATA = PORT_B_WIDTH >= 18 ? dout_b[17:0] :
	                            PORT_B_WIDTH >= 9  ? {dout_b[7], dout_b[16:9]} :
	                            PORT_B_WIDTH >= 4  ? dout_b[6:3] :
	                            PORT_B_WIDTH >= 2  ? dout_b[2:1] : dout_b[0];

	// DWSEL is a thermometer code: 0=x18, 01000=x9, then progressively
	// narrower modes.  The x18 oracle uses the nine word-address bits in
	// AddressA[12:4] with the low nibble at 1111; narrow modes use the native
	// low-address representation seen in the vendor SERV register-file cell.
	localparam [4:0] DWSEL = PORT_A_WIDTH >= 18 ? 5'b00000 :
	                         PORT_A_WIDTH >= 9  ? 5'b01000 :
	                         PORT_A_WIDTH >= 4  ? 5'b01100 :
	                         PORT_A_WIDTH >= 2  ? 5'b01110 : 5'b01111;
	localparam [4:0] DWSEL_B = PORT_B_WIDTH >= 18 ? 5'b00000 :
	                           PORT_B_WIDTH >= 9  ? 5'b01000 :
	                           PORT_B_WIDTH >= 4  ? 5'b01100 :
	                           PORT_B_WIDTH >= 2  ? 5'b01110 : 5'b01111;
	wire [12:0] phys_addr_a = PORT_A_WIDTH >= 18 ? {PORT_A_ADDR[8:0], 4'b1111} :
	                          PORT_A_WIDTH >= 9  ? {PORT_A_ADDR[9:0], 3'b111} :
	                          PORT_A_WIDTH >= 4  ? {PORT_A_ADDR[10:0], 2'b11} :
	                          PORT_A_WIDTH >= 2  ? {PORT_A_ADDR[11:0], 1'b1} : PORT_A_ADDR;
	wire [12:0] phys_addr_b = PORT_B_WIDTH >= 18 ? {PORT_B_ADDR[8:0], 4'b1111} :
	                          PORT_B_WIDTH >= 9  ? {PORT_B_ADDR[9:0], 3'b111} :
	                          PORT_B_WIDTH >= 4  ? {PORT_B_ADDR[10:0], 2'b11} :
	                          PORT_B_WIDTH >= 2  ? {PORT_B_ADDR[11:0], 1'b1} : PORT_B_ADDR;

	// A dynamically clock-enabled synchronous Port-B read uses the vendor's
	// input/output clock gates.  Constant-enable ROM probes also read with the
	// zero setting, but that does not qualify SERV's pulsed PORT_B_CLK_EN path.
	ALTA_BRAM9K #(
		.INIT_VAL(INIT), .PORTA_WIDTH(DWSEL), .PORTB_WIDTH(DWSEL_B), .CLKMODE(2'b00),
		.PORTB_CLKIN_EN(1'b1), .PORTB_CLKOUT_EN(1'b1)
	) _TECHMAP_REPLACE_ (
		.AddressA(phys_addr_a),
		.DataInA(din_a),
		.DataOutA(dout_a),
		.WeA(|PORT_A_WR_EN),                      // write when any write-enable bit set
		.ReA(1'b1),                               // always read
		.ByteEnA(2'b11),
		.AddressB(phys_addr_b),
		.DataInB(din_b),
		.DataOutB(dout_b),
		.WeB(|PORT_B_WR_EN),
		.ReB(1'b1),
		.ByteEnB(2'b11),
		.Clk0(PORT_A_CLK), .Clk1(PORT_B_CLK),
		.ClkEn0(PORT_A_CLK_EN), .ClkEn1(PORT_B_CLK_EN)
	);
endmodule
