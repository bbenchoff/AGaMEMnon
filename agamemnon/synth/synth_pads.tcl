# Usage
# tcl synth_pads.tcl {K} {out.json} {top}

set LUT_K 4
set TOP ""
if {$argc > 0} { set LUT_K [lindex $argv 0] }
if {$argc > 2} { set TOP [lindex $argv 2] }
yosys read_verilog -lib [file dirname [file normalize $argv0]]/prims.v
if {$TOP eq ""} { yosys hierarchy -check } else { yosys hierarchy -check -top $TOP }
yosys proc
yosys flatten
yosys tribuf -logic
yosys deminout
yosys synth -run coarse
# map inferred memories to the AGRV2K block RAM (ALTA_BRAM9K) before the generic FF fallback; leftover
# small/odd memories still fall through to memory_map -> FFs.
# A 9-Kibit hard block is always cheaper than lowering a matching RAM into
# slices on this device.  Give soft RAM a deliberately high cost so narrow,
# deep memories (notably SERV's 512x2 register file) cannot be misclassified
# as a distributed-memory win and expanded into thousands of LUT/FF cells.
yosys memory_libmap -logic-cost-ram 100000 -lib [file dirname [file normalize $argv0]]/ag32_brams.txt
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
