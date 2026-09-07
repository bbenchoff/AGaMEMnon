# Shared constant BRAM input placement

Required constant-zero address and active data inputs may share one LUT
source. The dynamic per-pin fixed source locations are incompatible when
applied independently to that one cell, even when the loaded graph has a BEL
reaching all its terminals.

The packer now distinguishes a defined-zero combinational F output from a
dynamic or unproven source. Such constants use the intersection of available
graph-reachable BELs, still honoring explicit BEL requests. Dynamic source
restrictions, controls, and all other legality checks remain. Constants keep
ordinary F presentation rather than inheriting a pin-specific OMUX override.
There is no new environment switch or name-dependent exception.

Focused native tests: **71 passed, no skips**. Coverage includes both BRAM
ports, five widths, shared required zeros, active zero data, semantic naming,
explicit constraints, and negative registered/dynamic/unknown cases. The
pre-repair address matrix and renamed-source case reproduced 21 failures.
The broader native/synthesis suite passes **263 with one optional overlay
check skipped**; that check passes separately with the native source path
explicitly configured. Admission/feature tests pass **55**. These are focused
checks, not a new complete all-platform regression run.

A controlled L48 experiment with a working clock source preserves the complete
original parity oracle in three runs when the forced constant-source selector
is cleared. A fresh original RTL build with this repair routes at default
settings. Its research-only INIT-restored image reproduces those witnessed
bytes exactly. This is not an ordinary admitted initialized build: the public
initialized-read fence remains pending broader behavior qualification.
