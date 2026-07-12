# Usage
# tcl synth_generic.tcl {K} {out.json}

set LUT_K 4
if {$argc > 0} { set LUT_K [lindex $argv 0] }
yosys read_verilog -lib [file dirname [file normalize $argv0]]/prims.v
yosys hierarchy -check
yosys proc
yosys flatten
yosys tribuf -logic
yosys deminout
yosys synth -run coarse
# map inferred memories to the AGRV2K block RAM (ALTA_BRAM9K) before the generic FF fallback; leftover
# small/odd memories still fall through to memory_map -> FFs.
yosys memory_libmap -lib [file dirname [file normalize $argv0]]/ag32_brams.txt
yosys techmap -map [file dirname [file normalize $argv0]]/ag32_brams_map.v
yosys memory_map
yosys opt -full
# HW-CARRY (opt-in, AGAMEMNON_HW_CARRY): lower `$alu` (from `synth -run coarse`) to a ripple chain of
# AG32_FA blackboxes BEFORE the generic `$alu` techmap shreds `+` into carry-less LUT4s -- so the carry
# rides the slice's DEDICATED Cin/Cout hardware (fused by the uarch's pack_carries). AG32_FA is read as
# `-lib` so it survives abc as an instance. Default OFF -> the proven routed-inter-tile "spread" carry flow
# is byte-for-byte unchanged (regression suite covers the default path). NOTE: dedicated HW carry is
# silicon-BANKED (the own-Q/vcc-entanglement wall); this wires the path end-to-end as a coherent opt-in.
if {[info exists ::env(AGAMEMNON_HW_CARRY)]} {
    yosys read_verilog -lib [file dirname [file normalize $argv0]]/ag32_carry_prims.v
    yosys techmap -map [file dirname [file normalize $argv0]]/ag32_carry_map.v
    yosys opt -fast
}
yosys techmap -map +/techmap.v
yosys opt -fast
yosys dfflegalize -cell \$_DFF_P_ 0
yosys abc -lut $LUT_K -dress
yosys clean
yosys techmap -D LUT_K=$LUT_K -map [file dirname [file normalize $argv0]]/cells_map.v
yosys clean
yosys hierarchy -check
yosys stat

yosys iopadmap -bits -inpad GENERIC_IOB O:PAD -outpad GENERIC_IOB I:PAD
yosys clean
yosys stat
if {$argc > 1} { yosys write_json [lindex $argv 1] }
