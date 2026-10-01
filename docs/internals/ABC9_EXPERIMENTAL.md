# Experimental ABC9 LUT4 mapping

`agamemnon/synth/abc9_ag32.tcl` supplies an opt-in replacement for the final
classic `abc -lut $LUT_K -dress` pass.  It is deliberately not enabled by the
default flow.  The caller must source the hook after `dfflegalize`, run
`agamemnon_abc9_map $SCRIPT_DIR $LUT_K`, then continue with the existing
`cells_map.v` lowering:

```tcl
if {[info exists ::env(AGAMEMNON_ABC9)] && $::env(AGAMEMNON_ABC9) eq "1"} {
    source $SCRIPT_DIR/abc9_ag32.tcl
    agamemnon_abc9_map $SCRIPT_DIR $LUT_K
} else {
    yosys abc -lut $LUT_K -dress
}
```

`AGAMEMNON_ABC9` is a strict `0` or `1` selector. Unset and `0` use classic
ABC; `1` enables this experimental hook. Other values are rejected. This only
normalizes configuration selection and makes no area, routing, timing, or
silicon-performance claim.

The model maps ordinary combinational logic to the same `$lut` and then `LUT`
path used by the classic flow.  Its one cost unit is one AGRV2K LUT4.  Its LUT
input delays mirror the existing conservative nextpnr model: A/B/C/D to
`LutOut` are 608/565/474/149 ps.  The public model records these as derived
maxima from decoded timing data. `archgen.py` binds A/B/C/D to
`GENERIC_SLICE.I[0..3]`, and `cells_map.v` retains that `$lut` input order.
The packer may later make a legal input/INIT-axis permutation, so this ABC9
ranking does not prove a final physical pin assignment or timing gain.

No timing assertion is made for placement, routing, output multiplexing, a
particular device speed grade, or silicon.  The public measured routing table
is explicitly one design and one PVT point, so it is not inserted into an ABC9
cell model.  The recovered library does contain plain CLK-to-Q values, but the
ABC9 hook intentionally does not use `-dff`: plain DFF, DFFE/control handling,
initialization, and reset admission remain the existing synthesis and packer
responsibility.  `AG32_FA` stays a black-box dedicated carry primitive and is
never modeled as an ABC9 box; its CIN/COUT packing remains on its existing
qualified path.

Use the normal functional and place/route checks for each comparison.  ABC9
cell cost and its internal LUT delay ranking are model evidence only; neither
is a timing-closure or hardware-qualification claim.

On the pinned WSL Yosys 0.33 used for the initial hook check, full
`synth_pads.tcl` A/B runs had identical mapped counts: `comb.v` used one LUT;
`native-clock-enable-xor3/clken_fixture_core.v` used 67 LUTs, 44 DFFs, and 59
IOBs; and `carry_add4.v` with `AGAMEMNON_HW_CARRY=1` kept five `AG32_FA`
cells.  These are synthesis-only observations, bounded to those sources and
tool version. They demonstrate compatibility and carry preservation, not an
area or timing improvement.
