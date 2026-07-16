# Usage
# tcl synth_generic.tcl {K} {out.json} {top}

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
yosys memory_map
yosys opt -full
yosys techmap -map +/techmap.v
yosys opt -fast
yosys dfflegalize -cell \$_DFF_P_ 0
yosys abc -lut $LUT_K -dress
yosys clean
yosys techmap -D LUT_K=$LUT_K -map [file dirname [file normalize $argv0]]/cells_map.v
yosys clean
yosys hierarchy -check
yosys stat

if {$argc > 1} { yosys write_json [lindex $argv 1] }
