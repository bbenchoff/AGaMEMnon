# TMUX9 images after register fanout and AddressA corrections

The general register fanout repair changes X14Y8 CFG_OMUX2[2] from F to Q on
a used registered-output branch. The four source profiles also incorporate
the AddressA[8] repair, clearing X13Y4 CFG_IMUX1[7] and [11]. An independent
image comparison attributed every changed payload bit to these fields and
checked the image integrity, header, unchanged routed inputs and INIT bits.

Two controlled SRAM-only batches compared the old and corrected images twice.
All32 captures and6 known-good controls passed; both final resets passed. Raw
502-word mailbox logs were independently reparsed: all500 data samples match
the expected hold/write polarity and both activity observers vary. The first
batch covers all four retained source profiles. The second covers two zero-INIT
checkpoints, with the initialized source counterparts as polarity controls.

The machine-readable record `registered_bram_tmux9_requalification_20260926.json`
binds exact hashes and captures to published AG32-Docs evidence at commit
1bca9942957803384a8784040c4ffd02e15aff21. Historical records remain unchanged.
The CLI, legacy clock admission and independent wheel/archive checks use the
new qualified hashes. No route or source admission restriction is relaxed.

This is fixed-address, one-lane write/hold evidence for six retained physical
implementations. Initialized historical checkpoints remain refused. Fresh source
builds, general memories, collisions and unrelated modes are not qualified by
these batches. Final candidate release gates remain required.
