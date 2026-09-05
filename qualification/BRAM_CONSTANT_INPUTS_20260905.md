# Required BRAM constant inputs

The native packer now preserves required constant-zero address and active data
inputs instead of treating them as unconnected default-low terminals. A
controlled L48 x1 experiment showed that an unselected AddressA[3] reads high:
removing only its ground selector broke an initialized read, and moving the
expected data to the corresponding high-address region restored the complete
oracle in three interleaved trials. This is not a general BRAM qualification.

Required zero pins retain their shared ground net. Existing read-only data,
inactive-port, and width-padding trimming remains in place. Characterized
constant-high defaults and the constant-write-enable refusal are unchanged.
No graph, selector encoding, or initialized-read safety fence changes.

Verification on the implementation source:

- New native regression: 20 previously failing required-zero cases and 12
  passing controls become 32 passing cases, spanning both ports and all five
  admitted widths.
- Combined native endpoint, carry, soft-ripple, BRAM and synthesis suite:
  237 passed, zero skipped, 215.53 seconds.
- Packing/loading failure-summary coverage plus existing router diagnostics:
  93 passed, 0.35 seconds. Existing stage detection now feeds the escalation
  summary instead of reporting a known packing refusal as an unknown failure.

The fresh initialized ROM still does not emit. Its shared ground source has
incompatible fixed source-slot requirements in BRAM pin packing. A separate
equivalent per-pin zero-source replication experiment passes those assignments
but refuses simultaneous corridor allocation for AddressA[11]. These are
pre-routing packing failures, not router timeouts. Both experiments retain all
required constants; discarding them to regain routability would restore the
correctness defect.

The earlier full Windows suite belongs to the preceding commit, not this
change. Full-suite validation, a general constant-delivery solution, fresh
open-generated images, and hardware qualification remain required. No public
main promotion or initialized-read support claim accompanies this change.
