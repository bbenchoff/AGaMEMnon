# Optional ABC9 hook for synth_pads.tcl, intended to be sourced immediately
# after dfflegalize and before the existing `abc -lut $LUT_K -dress` command.
#
# Invocation from the caller (do not source this in the retained/classic path):
#   source $SCRIPT_DIR/abc9_ag32.tcl
#   agamemnon_abc9_map $SCRIPT_DIR $LUT_K
# ABC9 emits ordinary `$lut` cells, so the caller then continues with its
# existing `cells_map.v` techmap.  The
# procedure leaves AG32_FA and all flop/control cells untouched because it
# deliberately does not use abc9 -dff.  This preserves dedicated carry and
# DFFE semantics already owned by the normal legalisation/packer stages.

proc agamemnon_abc9_map {script_dir lut_k} {
    if {$lut_k != 4} {
        error "AGAMEMNON ABC9 model supports only the AGRV2K LUT4 (got LUT_K=$lut_k)"
    }
    yosys read_verilog -lib -specify $script_dir/ag32_abc9_model.v
    yosys abc9
    yosys clean
}
