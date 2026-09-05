# Preserve explicit memory placement through memory_libmap. That pass creates
# new library cells and need not retain source attributes. Map each constrained
# memory separately, then identify its outputs by selection-set difference;
# generated cell names and the mapper's internal naming convention are irrelevant.
# One BEL cannot satisfy a memory split across several physical blocks.
proc agamemnon_preserve_memory_bels {synth_dir} {
    set fh [file tempfile scratch]
    close $fh
    # Yosys rejects unsetting a selection that was never created. Initialize
    # every scratch selection so early returns/errors preserve their diagnostic.
    set selection_names {agm_constrained_memories agm_known_constrained agm_this_site agm_existing_blocks agm_new_blocks}
    yosys select -none
    foreach name $selection_names { yosys select -set $name % }
    yosys select -clear
    try {
        yosys select -set agm_constrained_memories t:\$mem t:\$mem_v2 %u a:BEL %i
        yosys select -write $scratch @agm_constrained_memories
        set fh [open $scratch r]
        set constrained [string trim [read $fh]]
        close $fh
        if {$constrained eq ""} { return }

        # Read physical sites from the same packaged device table as the engine.
        set fh [open [file join $synth_dir .. chipdb bram9k_bel.csv] r]
        set sites {}
        gets $fh header
        if {[string trim $header] ne "port,bit,x,y,res"} {
            close $fh
            error "invalid BRAM BEL table header"
        }
        while {[gets $fh line] >= 0} {
            if {[string trim $line] eq ""} { continue }
            set fields [split [string trim $line] ,]
            set x [lindex $fields 2]
            set y [lindex $fields 3]
            if {[llength $fields] != 5 || ![string is integer -strict $x] ||
                    ![string is integer -strict $y]} {
                close $fh
                error "invalid BRAM BEL table coordinates"
            }
            dict set sites "X${x}Y${y}_BRAM" 1
        }
        close $fh
        yosys select -none
        yosys select -set agm_known_constrained %
        yosys select -clear
        set assignments {}
        foreach bel [lsort [dict keys $sites]] {
            yosys select -set agm_this_site @agm_constrained_memories a:BEL=$bel %i
            yosys select -set agm_known_constrained @agm_known_constrained @agm_this_site %u
            yosys select -write $scratch @agm_this_site
            set fh [open $scratch r]
            foreach memory [split [string trim [read $fh]] "\n"] {
                if {$memory ne ""} { lappend assignments [list $memory $bel] }
            }
            close $fh
        }
        yosys select -write $scratch @agm_constrained_memories @agm_known_constrained %d
        set fh [open $scratch r]
        set unknown [string trim [read $fh]]
        close $fh
        if {$unknown ne ""} {
            error "AGAMEMNON memory BEL constraint is not a device BRAM site: $unknown"
        }
        foreach assignment $assignments {
            lassign $assignment memory bel
            yosys select -set agm_existing_blocks t:\$__ALTA_BRAM9K_
            # select -read consumes exact object names, avoiding wildcard
            # interpretation of bracketed/escaped source identifiers.
            set fh [open $scratch w]
            puts $fh $memory
            close $fh
            yosys select -read $scratch
            yosys select -assert-count 1 %
            yosys memory_libmap -logic-cost-ram 100000 -lib $synth_dir/ag32_brams.txt
            yosys select -clear
            yosys select -set agm_new_blocks t:\$__ALTA_BRAM9K_ @agm_existing_blocks %d
            yosys select -write $scratch @agm_new_blocks
            set fh [open $scratch r]
            set blocks [string trim [read $fh]]
            close $fh
            if {$blocks eq "" || [llength [split $blocks "\n"]] != 1} {
                error "AGAMEMNON memory BEL constraint requires exactly one physical block: $memory -> $bel; mapped blocks: $blocks"
            }
            yosys setattr -set BEL \"$bel\" @agm_new_blocks
            puts "AGAMEMNON preserved memory BEL: $memory -> $blocks at $bel"
        }
    } finally {
        foreach name $selection_names {
            yosys select -unset $name
        }
        yosys select -clear
        file delete -force $scratch
    }
}
