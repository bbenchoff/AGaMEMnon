# Usage
# tcl synth_pads.tcl {K} {out.json} {top}

set LUT_K 4
set TOP ""
set OUT ""
if {[info exists ::env(AGAMEMNON_YOSYS_LUT_K)]} {
    set LUT_K $::env(AGAMEMNON_YOSYS_LUT_K)
} elseif {[info exists argc] && $argc > 0} {
    set LUT_K [lindex $argv 0]
}
if {[info exists ::env(AGAMEMNON_YOSYS_TOP)]} {
    set TOP $::env(AGAMEMNON_YOSYS_TOP)
} elseif {[info exists argc] && $argc > 2} {
    set TOP [lindex $argv 2]
}
if {[info exists ::env(AGAMEMNON_YOSYS_JSON)]} {
    set OUT $::env(AGAMEMNON_YOSYS_JSON)
} elseif {[info exists argc] && $argc > 1} {
    set OUT [lindex $argv 1]
}
set SCRIPT_DIR [file dirname [file normalize [info script]]]
yosys read_verilog -lib $SCRIPT_DIR/prims.v
# Shared-control primitives live in their own file and are read only when the
# feature is on.  Putting them in prims.v changed the synthesised design even
# with the feature off: the extra library modules shift Yosys's autoidx, which
# moves generated cell names in the top module, and the output JSON stops being
# byte-identical.  Measured, not assumed.
if {[info exists ::env(AGRV2K_SHARED_CONTROL_ENABLE)]} {
    yosys read_verilog -lib $SCRIPT_DIR/prims_control.v
}
# Positional Verilog arguments are initially parsed as `$abstract\...` modules.
# `hierarchy -check` alone does not derive one on Yosys 0.33, so a build that
# omitted --top synthesized the primitive library/empty design and could emit a
# valid-looking blank image. Explicit tops already derived correctly; infer the
# sole/strongest root for the normal CLI default.
if {$TOP eq ""} { yosys hierarchy -check -auto-top } else { yosys hierarchy -check -top $TOP }
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
source $SCRIPT_DIR/memory_bel.tcl
agamemnon_preserve_memory_bels $SCRIPT_DIR
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
# HW-CARRY (AGAMEMNON_HW_CARRY): lower eligible `$alu` cells (from `synth -run coarse`) to ripple chains
# of AG32_FA blackboxes BEFORE the generic `$alu` techmap shreds the remaining arithmetic into LUT4s.
# The qualified physical resource is either one 33-site corridor (one seed plus at most 32 arithmetic
# stages) or multiple complete seeded chains occupying at most nine same-tile sites.
# Selection therefore happens here, while an unselected `$alu` can still degrade through the ordinary
# LUT path.  Mapping every `$alu` and discovering the aggregate size in the packer made one oversized or
# additional chain refuse the entire build after graceful degradation was no longer possible.
if {[info exists ::env(AGAMEMNON_HW_CARRY)]} {
    # Order deterministically by greatest useful width, then canonical cell name. The parameter selector
    # is evaluated by Yosys (rather than inferred from names), and widths above 32 are deliberately left
    # for the generic techmap below. If the largest candidate needs the long corridor, allocate just that
    # chain. Otherwise a nine-entry dynamic program fills the same-tile footprint with complete
    # (width + seed) chains, maximizing useful arithmetic stages while never splitting a chain.
    set _carry_candidates {}
    set _carry_select_file ""
    set _carry_select_fh [file tempfile _carry_select_file]
    close $_carry_select_fh
    for {set _carry_width 32} {$_carry_width >= 1} {incr _carry_width -1} {
        yosys select -write $_carry_select_file t:\$alu r:Y_WIDTH=$_carry_width %i
        set _carry_select_fh [open $_carry_select_file r]
        set _carry_width_candidates {}
        foreach _carry_line [split [read $_carry_select_fh] "\n"] {
            set _carry_line [string trim $_carry_line]
            if {$_carry_line ne ""} { lappend _carry_width_candidates $_carry_line }
        }
        close $_carry_select_fh
        foreach _carry_line [lsort -dictionary $_carry_width_candidates] {
            lappend _carry_candidates [list $_carry_width $_carry_line]
        }
    }
    set _carry_choices {}
    set _carry_sites 0
    if {[llength $_carry_candidates] > 0} {
        set _carry_largest [lindex [lindex $_carry_candidates 0] 0]
        if {$_carry_largest > 8} {
            lappend _carry_choices [lindex $_carry_candidates 0]
            set _carry_sites [expr {$_carry_largest + 1}]
        } else {
            array set _carry_dp_value {}
            array set _carry_dp_choices {}
            for {set _carry_capacity 0} {$_carry_capacity <= 9} {incr _carry_capacity} {
                set _carry_dp_value($_carry_capacity) -1
                set _carry_dp_choices($_carry_capacity) {}
            }
            set _carry_dp_value(0) 0
            foreach _carry_candidate $_carry_candidates {
                set _carry_width [lindex $_carry_candidate 0]
                set _carry_cost [expr {[lindex $_carry_candidate 0] + 1}]
                for {set _carry_capacity [expr {9 - $_carry_cost}]} {$_carry_capacity >= 0} {incr _carry_capacity -1} {
                    if {$_carry_dp_value($_carry_capacity) < 0} { continue }
                    set _carry_new_capacity [expr {$_carry_capacity + $_carry_cost}]
                    set _carry_new_value [expr {$_carry_dp_value($_carry_capacity) + $_carry_width}]
                    if {$_carry_new_value > $_carry_dp_value($_carry_new_capacity)} {
                        set _carry_dp_value($_carry_new_capacity) $_carry_new_value
                        set _carry_dp_choices($_carry_new_capacity) [concat $_carry_dp_choices($_carry_capacity) [list $_carry_candidate]]
                    }
                }
            }
            set _carry_best_value -1
            for {set _carry_capacity 0} {$_carry_capacity <= 9} {incr _carry_capacity} {
                if {$_carry_dp_value($_carry_capacity) > $_carry_best_value} {
                    set _carry_best_value $_carry_dp_value($_carry_capacity)
                    set _carry_sites $_carry_capacity
                    set _carry_choices $_carry_dp_choices($_carry_capacity)
                }
            }
            array unset _carry_dp_value
            array unset _carry_dp_choices
        }
    }
    if {[llength $_carry_choices] > 0} {
        set _carry_select_fh [open $_carry_select_file w]
        set _carry_stages 0
        foreach _carry_choice $_carry_choices {
            incr _carry_stages [lindex $_carry_choice 0]
            puts $_carry_select_fh [lindex $_carry_choice 1]
        }
        close $_carry_select_fh
        yosys select -read $_carry_select_file
        yosys select -set agamemnon_hw_carry %
        yosys select -clear
        yosys read_verilog -lib $SCRIPT_DIR/ag32_carry_prims.v
        yosys techmap -map $SCRIPT_DIR/ag32_carry_map.v @agamemnon_hw_carry
        yosys select -unset agamemnon_hw_carry
        yosys opt -fast
        puts "AGAMEMNON carry allocation: dedicated [llength $_carry_choices] chain(s), $_carry_stages arithmetic stages, $_carry_sites seeded sites; remaining arithmetic uses LUT fallback"
    } else {
        puts "AGAMEMNON carry allocation: no chain fits the qualified 32-stage corridor; arithmetic uses LUT fallback"
    }
    file delete -force $_carry_select_file
}
yosys techmap -map +/techmap.v
yosys opt -fast
# Clock enables and synchronous resets do not require a slice control pin:
# both are exactly representable as muxes on D feeding an ordinary positive-
# edge FF.  Lower only the fine-grain families that have no asynchronous
# control.  In particular, do not select the longer $_DFFE_* forms carrying
# an asynchronous reset, nor $_DFFSRE_* / $_ALDFFE_*; the fail-closed guard
# below must still see and reject those physical-control combinations.
# AGRV2K_SHARED_CONTROL_ENABLE keeps exactly one of these forms: $_DFFE_PP_,
# positive-edge clock with an active-high enable.  That is the only shape the
# decoded silicon selector covers -- CFG_CLKMUX<z> picks which of the tile's two
# clock-enable lines a slice takes, correlated 416/416 against the line actually
# carrying each register's `ena`.  Every other family stays unmapped:
#   * $_DFFE_NN_/_NP_/_PN_  negative clock or active-low enable; the polarity is
#     not decoded and dfflegalize would silently invert it.
#   * $_SDFF*               synchronous reset, whose per-slice line selector is
#     NOT established -- all 424 sync observations in the corpus sit on line 0,
#     so nothing discriminates CFG_ASYNCMUX<z> for that family.
# With the flag unset the list is byte-for-byte what it was, so an ordinary
# build lowers exactly what it lowered before and no emitted image moves.
set _shared_control_enable [info exists ::env(AGRV2K_SHARED_CONTROL_ENABLE)]
# Synchronous reset has no decoded tile control line.  Remove only that
# control first, then let opt recognize the remaining hold muxes as native
# enables.  `-nosdff` is essential: it prevents opt from rebuilding the
# synchronous-reset forms which the frontend deliberately does not admit.
# The order preserves source priority: reset-first RTL becomes an enable whose
# D input is reset-selected, while enable-first RTL keeps its hold condition.
set _shared_control_srst_recovery 0
if {$_shared_control_enable} {
    # This is an experiment selector, separate from the established native
    # enable path.  Setting it to 0 retains the pre-recovery frontend exactly:
    # existing DFFE_PP_ cells remain eligible, while every synchronous-reset
    # family follows the legacy dffunmap fallback below. Recovery is off by
    # default so direct synthesis, project builds, and retained flows retain
    # the established mapping. The CLI's dual-candidate selector sets 1
    # explicitly only for its recovered candidate.
    set _shared_control_srst_recovery 0
    if {[info exists ::env(AGRV2K_SHARED_CONTROL_SRST_RECOVERY)]} {
        set _shared_control_srst_recovery $::env(AGRV2K_SHARED_CONTROL_SRST_RECOVERY)
    }
    if {$_shared_control_srst_recovery ne "0" &&
        $_shared_control_srst_recovery ne "1"} {
        error "AGRV2K_SHARED_CONTROL_SRST_RECOVERY must be 0 or 1 (got '$_shared_control_srst_recovery')"
    }
}
if {$_shared_control_srst_recovery} {
    # Sidecar for the CLI's bounded dual-candidate selector.  It records an
    # exact pre-recovery population, avoiding a source-text heuristic and
    # letting ordinary enable-only designs retain their single historical run.
    if {$OUT ne ""} {
        set _srst_eligible_file "${OUT}.srst-recovery-select.txt"
        yosys select -write $_srst_eligible_file t:\$_SDFF_* t:\$_SDFFE_* t:\$_SDFFCE_*
        set _srst_eligible_fh [open $_srst_eligible_file r]
        set _srst_eligible_count 0
        foreach _srst_eligible_line [split [read $_srst_eligible_fh] "\n"] {
            if {[string length [string trim $_srst_eligible_line]] > 0} { incr _srst_eligible_count }
        }
        close $_srst_eligible_fh
        file delete -force $_srst_eligible_file
        set _srst_sidecar_fh [open "${OUT}.srst-recovery.json" w]
        puts $_srst_sidecar_fh "{\"schema\":\"agamemnon.srst-recovery.v1\",\"eligible_cells\":$_srst_eligible_count}"
        close $_srst_sidecar_fh
    }
    yosys dffunmap -srst-only
    yosys opt -full -nosdff
}
set _dffunmap_families [list t:\$_DFFE_NN_ t:\$_DFFE_NP_ t:\$_DFFE_PN_]
if {!$_shared_control_enable} {
    lappend _dffunmap_families t:\$_DFFE_PP_
}
lappend _dffunmap_families t:\$_SDFF_* t:\$_SDFFE_* t:\$_SDFFCE_*
yosys dffunmap {*}$_dffunmap_families
# Shared slice controls are a typed frontend boundary.  Inspect every remaining
# fine-grain controlled-FF form before dfflegalize is allowed to invert its
# polarity or otherwise erase asynchronous source semantics.  N4.1 keeps
# only the existing plain positive-edge FF and the one desk-oracle form:
# positive-edge, active-high asynchronous clear-to-zero.  The latter remains
# an internal $_DFF_PP0_ cell in JSON; nextpnr rejects it with the explicit
# unsupported-physical-control diagnostic until graph/codewords/HIL exist.
set _shared_control_all_file ""
set _shared_control_all_fh [file tempfile _shared_control_all_file]
close $_shared_control_all_fh
set _shared_control_allowed_file ""
set _shared_control_allowed_fh [file tempfile _shared_control_allowed_file]
close $_shared_control_allowed_fh
yosys select -write $_shared_control_all_file \
    t:\$_DFF_* t:\$_DFFE_* t:\$_DFFSR_* t:\$_DFFSRE_* \
    t:\$_SDFF_* t:\$_SDFFE_* t:\$_SDFFCE_* \
    t:\$_ALDFF_* t:\$_ALDFFE_*
set _shared_control_allowed_types [list t:\$_DFF_P_ t:\$_DFF_PP0_]
if {$_shared_control_enable} {
    lappend _shared_control_allowed_types t:\$_DFFE_PP_
}
yosys select -write $_shared_control_allowed_file \
    {*}$_shared_control_allowed_types
set _shared_control_allowed_fh [open $_shared_control_allowed_file r]
set _shared_control_allowed {}
foreach _shared_control_cell [split [read $_shared_control_allowed_fh] "\n"] {
    set _shared_control_cell [string trim $_shared_control_cell]
    if {$_shared_control_cell ne ""} {
        lappend _shared_control_allowed $_shared_control_cell
    }
}
close $_shared_control_allowed_fh
set _shared_control_all_fh [open $_shared_control_all_file r]
set _shared_control_unsupported {}
foreach _shared_control_cell [split [read $_shared_control_all_fh] "\n"] {
    set _shared_control_cell [string trim $_shared_control_cell]
    if {$_shared_control_cell ne "" &&
        [lsearch -exact $_shared_control_allowed $_shared_control_cell] < 0} {
        lappend _shared_control_unsupported $_shared_control_cell
    }
}
close $_shared_control_all_fh
file delete -force $_shared_control_all_file $_shared_control_allowed_file
if {[llength $_shared_control_unsupported] > 0} {
    puts stderr "AGAMEMNON shared control: unsupported register control/polarity/value; only plain positive-edge and bare active-high asynchronous clear-to-zero are accepted by the N4.1 frontend: $_shared_control_unsupported"
    error "unsupported shared register control"
}
set _dfflegalize_cells [list -cell \$_DFF_P_ 0 -cell \$_DFF_PP0_ 0]
if {$_shared_control_enable} {
    # Keep only enable groups large enough to justify one of the tile's two
    # shared lines.  This is an explicit build setting so experiments can
    # measure 2/4/8 without changing the no-native or retained-replay flow.
    # Reject non-positive values here rather than silently treating a typo as
    # a different architecture policy.
    set _shared_control_mince 4
    if {[info exists ::env(AGRV2K_SHARED_CONTROL_MINCE)]} {
        set _shared_control_mince $::env(AGRV2K_SHARED_CONTROL_MINCE)
    }
    if {![string is integer -strict $_shared_control_mince] ||
        $_shared_control_mince <= 0} {
        error "AGRV2K_SHARED_CONTROL_MINCE must be a positive integer (got '$_shared_control_mince')"
    }
    lappend _dfflegalize_cells -cell \$_DFFE_PP_ 0
    lappend _dfflegalize_cells -mince $_shared_control_mince
}
yosys dfflegalize {*}$_dfflegalize_cells
# Legalization may unmap an undersized enable group.  Stamp only after it has
# finished, so every CLOCK_ENABLE_POS tag has a real DFFE cell and a real EN
# port for the packer to consume.  The existing async-clear tag is likewise
# applied after legalization for one uniform final-cell invariant.
yosys setattr -set AGRV2K_SHARED_CONTROL_MODE \
    \"ASYNC_CLEAR_POS_ZERO\" t:\$_DFF_PP0_
if {$_shared_control_enable} {
    yosys setattr -set AGRV2K_SHARED_CONTROL_MODE \
        \"CLOCK_ENABLE_POS\" t:\$_DFFE_PP_
}
set _agamemnon_abc9 0
if {[info exists ::env(AGAMEMNON_ABC9)]} {
    set _agamemnon_abc9 $::env(AGAMEMNON_ABC9)
}
if {$_agamemnon_abc9 ne "0" && $_agamemnon_abc9 ne "1"} {
    error "AGAMEMNON_ABC9 must be 0 or 1 (got '$_agamemnon_abc9')"
}
if {$_agamemnon_abc9} {
    source $SCRIPT_DIR/abc9_ag32.tcl
    agamemnon_abc9_map $SCRIPT_DIR $LUT_K
} else {
    yosys abc -lut $LUT_K -dress
}
yosys clean
set _techmap_maps [list -map $SCRIPT_DIR/cells_map.v]
if {$_shared_control_enable} {
    lappend _techmap_maps -map $SCRIPT_DIR/cells_map_control.v
}
yosys techmap -D LUT_K=$LUT_K {*}$_techmap_maps
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
