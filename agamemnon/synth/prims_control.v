// Primitives for the shared-control path.  Read ONLY when
// AGRV2K_SHARED_CONTROL_ENABLE is set.
//
// Kept out of prims.v deliberately: prims.v is read with `-lib` on every build,
// and adding modules there changed the synthesised design even with the feature
// off -- the extra blackboxes shift Yosys's autoidx, so generated cell names in
// the top module move and the JSON is no longer byte-identical.  A build with
// the flag unset must produce exactly the bytes it produced before, because the
// retained byte gate compares emitted images.

// Clock-enable flip-flop.  The enable is NOT a slice pin: it terminates on one
// of the tile's two shared clock-enable lines, and CFG_CLKMUX<z> selects which
// line the slice consumes.  The packer lifts EN off the slice and onto a tile
// control cell.
module DFFE (
	input CLK, EN, D,
	output reg Q
);
	initial Q = 1'b0;
	always @(posedge CLK)
		if (EN)
			Q <= D;
endmodule

// One shared clock-enable line of one LogicTile.  A pure sink: the routed
// enable net ends here and no wire leaves it.
(* blackbox *)
module AGRV2K_TILE_CONTROL (
	input I
);
endmodule
