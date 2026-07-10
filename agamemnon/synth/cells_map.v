module \$lut (A, Y);
	parameter WIDTH = 0;
	parameter LUT = 0;
	input [WIDTH-1:0] A;
	output Y;

	localparam rep = 1<<(`LUT_K-WIDTH);

	// Pad the input to the full K bits so the LUT's `I` port is ALWAYS K-wide and the nextpnr frontend
	// splits it into I[0]..I[K-1]. A sub-K-input LUT (e.g. a 1-input inverter/buffer, ubiquitous in shift
	// registers and SERV) would otherwise get a width-1 scalar port named `I`, which lut_to_lc's per-index
	// I[i] move misses -> stale net user -> nextpnr INTERNAL CHECK failure. INIT is replicated ({rep{LUT}})
	// so the padded high inputs (0) don't change the function.
	LUT #(.K(`LUT_K), .INIT({rep{LUT}})) _TECHMAP_REPLACE_ (.I({{(`LUT_K-WIDTH){1'b0}}, A}), .Q(Y));
endmodule

module  \$_DFF_P_ (input D, C, output Q); DFF  _TECHMAP_REPLACE_ (.D(D), .Q(Q), .CLK(C)); endmodule
