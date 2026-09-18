# Unused generated constants

The native packer can create shared or replicated constant slices whose last
consumer disappears during later carry, LUT or BRAM packing. These slices
still occupy placement resources even though they drive nothing.

Set `AGRV2K_PRUNE_UNUSED_CONSTANTS=1` for experimental reclamation. Only the
literal value `1` enables it; unset, empty and `0` preserve normal packing.
This option is independent of `AGRV2K_LOCAL_CONSTANTS` and works with shared
or replicated constants.

The cleanup tracks the exact cell IDs created by constant packing. It removes
an owned constant only when its output has no consumers or routing, its other
ports are disconnected, and it has no placement or keep constraints. Imported
constant cells are preserved, including cells with packer-like names. Constants
that still supply BRAM inputs, arithmetic inputs or other live loads remain.

## Evidence and limits

Compiled tests check folded arithmetic operands, replication, live BRAM
addresses, and imported/fixed/kept constant cells. A four-stage registered
carry fixture needs six live slices; reclamation reduces its original eight
slices (eleven with local replication) to six without losing registers.

Fresh source packing of a 16-bit LFSR with an eight-bit prescaler saves two slices
with hard carry (44 to 42) or one with LUT carry (33 to 32), retaining all 24
registers. These are packing counts, not a general capacity or timing claim.

A fresh release-strict 32-bit accumulator build saves one slice (133 to 132),
retains all 78 registers and identical surviving logical connectivity, and
passes a model-backed 10 MHz board trial bracketed by vendor controls.
It also passes two valid 100 MHz trials. An earlier 100 MHz attempt stopped
at a failed vendor pre-control and is excluded from candidate results.
However, its changed placement fails two 110 MHz trials while the baseline
passes both; vendor controls pass throughout those trials. The option therefore
remains disabled by default. Area savings do not establish timing preservation:
rebuild and qualify each enabled design at its intended operating rate.
