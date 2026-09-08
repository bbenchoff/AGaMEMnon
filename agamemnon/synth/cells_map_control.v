// Techmap rule for the shared-control path.  Applied ONLY when
// AGRV2K_SHARED_CONTROL_ENABLE is set, for the same byte-identity reason
// prims_control.v is separate: an unused rule still perturbs the output.
module  \$_DFFE_PP_ (input D, C, E, output Q);
	DFFE _TECHMAP_REPLACE_ (.D(D), .Q(Q), .CLK(C), .EN(E));
endmodule
