# Usage
# tcl synth_pads.tcl {K} {out.json} {top}

set LUT_K 4
set TOP ""
set OUT ""
if {[info exists ::env(AGAMEMNON_YOSYS_LUT_K)]} {
    set LUT_K $::env(AGAMEMNON_YOSYS_LUT_K)
} elseif {$argc > 0} {
    set LUT_K [lindex $argv 0]
}
if {[info exists ::env(AGAMEMNON_YOSYS_TOP)]} {
    set TOP $::env(AGAMEMNON_YOSYS_TOP)
} elseif {$argc > 2} {
    set TOP [lindex $argv 2]
}
if {[info exists ::env(AGAMEMNON_YOSYS_JSON)]} {
    set OUT $::env(AGAMEMNON_YOSYS_JSON)
} elseif {$argc > 1} {
    set OUT [lindex $argv 1]
}
set SCRIPT_DIR [file dirname [file normalize [info script]]]
yosys read_verilog -lib $SCRIPT_DIR/prims.v
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
yosys memory_libmap -logic-cost-ram 100000 -lib $SCRIPT_DIR/ag32_brams.txt
yosys techmap -map $SCRIPT_DIR/ag32_brams_map.v
# SILENT-DEGRADATION GUARD: memory_map (next) irreversibly lowers any memory that
# memory_libmap declined to place on the hard ALTA_BRAM9K block into one flip-flop
# per bit plus an address-decode LUT tree -- e.g. a plain 512x1 memory with an
# asynchronous (combinational) read, which the block-RAM library cannot express
# (it only offers clocked "srsw" ports), silently expands into 512 DFFs + ~1000
# LUT4s with ZERO message under the default `-q` build (confirmed 2026-08;
# `memory_libmap` prints nothing when it simply never attempts a mapping, and
# `-q` suppresses the informational `stat` counts that would otherwise show it).
# "Small/odd memories still fall through to FFs" is an accepted, sized-based
# outcome (see the comment above); a full-size 9-Kibit-class memory silently
# doing the same is exactly the class of bug this flow must never hide. This
# does not fail the build here -- picking a working depth/width or forcing
# `(* ram_style = "block" *)` (which yosys itself then hard-errors on if it
# truly cannot fit, e.g. an async read) is a source change, not ours to make.
# SILENT-DEGRADATION GUARD (sidecar): raw stderr does NOT survive the build --
# the campaign runs yosys with `-q`, and cli.py's `run()` helper only prints
# captured stdout/stderr when the step itself *fails*, so on a passing build
# this warning used to vanish with nobody able to see it (the intermediate
# `$_mem_leftover_report` was written, read, and then unconditionally
# `file delete -force`d, throwing the finding away instead of keeping it).
# Fix: always write a stable, machine-readable sidecar
# (`<synth_json>.leftover_mem.json`, a JSON array of offending cell names,
# possibly empty) next to the synth JSON, independent of stdout/stderr
# capture. cli.py checks for this file immediately after the synth step and
# fails the build loudly unless the operator acknowledges it.
if {$OUT ne ""} {
    set _mem_leftover_report "$OUT.leftover_mem_select.txt"
    yosys select -write $_mem_leftover_report t:\$mem t:\$mem_v2
    set _mem_leftover_fh [open $_mem_leftover_report r]
    set _mem_leftover_lines [split [read $_mem_leftover_fh] "\n"]
    close $_mem_leftover_fh
    file delete -force $_mem_leftover_report
    set _mem_leftover_names {}
    foreach _line $_mem_leftover_lines {
        if {[string length [string trim $_line]] > 0} { lappend _mem_leftover_names $_line }
    }
    set _mem_leftover_sidecar "$OUT.leftover_mem.json"
    set _mem_leftover_json_items {}
    foreach _name $_mem_leftover_names {
        set _escaped [string map {"\\" "\\\\" "\"" "\\\""} $_name]
        lappend _mem_leftover_json_items "\"$_escaped\""
    }
    set _mem_leftover_json_fh [open $_mem_leftover_sidecar w]
    puts $_mem_leftover_json_fh "\[[join $_mem_leftover_json_items ", "]\]"
    close $_mem_leftover_json_fh
    if {[llength $_mem_leftover_names] > 0} {
        puts stderr "AGAMEMNON WARNING: [llength $_mem_leftover_names] memory cell(s) did NOT map to the ALTA_BRAM9K block RAM and are about to be lowered to individual flip-flops + LUT address decoding by memory_map: $_mem_leftover_names -- this can silently balloon LUT/FF usage (a common cause: an asynchronous/combinational read port, which the block-RAM library cannot express). Add `(* ram_style = \"block\" *)` to force it (yosys will then hard-error if the shape truly cannot fit) or restructure the read to be clocked."
    }
}
yosys memory_map
yosys opt -full
# HW-CARRY (opt-in, AGAMEMNON_HW_CARRY): lower `$alu` (from `synth -run coarse`) to a ripple chain of
# AG32_FA blackboxes BEFORE the generic `$alu` techmap shreds `+` into carry-less LUT4s -- so the carry
# rides the slice's DEDICATED Cin/Cout hardware (fused by the uarch's pack_carries). AG32_FA is read as
# `-lib` so it survives abc as an instance. Default OFF -> the proven routed-inter-tile "spread" carry flow
# is byte-for-byte unchanged (regression suite covers the default path). NOTE: dedicated HW carry is
# silicon-BANKED (the own-Q/vcc-entanglement wall); this wires the path end-to-end as a coherent opt-in.
if {[info exists ::env(AGAMEMNON_HW_CARRY)]} {
    yosys read_verilog -lib $SCRIPT_DIR/ag32_carry_prims.v
    yosys techmap -map $SCRIPT_DIR/ag32_carry_map.v
    yosys opt -fast
}
yosys techmap -map +/techmap.v
yosys opt -fast
yosys dfflegalize -cell \$_DFF_P_ 0
yosys abc -lut $LUT_K -dress
yosys clean
yosys techmap -D LUT_K=$LUT_K -map $SCRIPT_DIR/cells_map.v
yosys clean
yosys hierarchy -check
yosys stat

if {![info exists ::env(AGAMEMNON_INTERNAL_PORTS)]} {
    yosys iopadmap -bits -inpad GENERIC_IOB O:PAD -outpad GENERIC_IOB I:PAD \
        -tinoutpad GENERIC_IOB EN:O:I:PAD
    yosys clean
    yosys stat
}
if {$OUT ne ""} { yosys write_json $OUT }
