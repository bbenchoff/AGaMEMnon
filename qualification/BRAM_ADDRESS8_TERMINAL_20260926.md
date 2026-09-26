# BRAM AddressA[8] selector correction

The exact X13Y4_RMUX28 -> X13Y4_IMUX04 override previously set local selector
bits 5,7,10,11. Its evidence came from a constant-address x18 configuration.
On the retained dynamic x1 OUTREG0 design, the completed-read-round checker
fails. Clearing only bits 7 and 11, with the required CRC update, passes both
hardware repetitions. The original fails both repetitions. Both same-placement
vendor comparisons, two original vendor controls, nine shared references and
all 17 recovery checks pass. SRAM only; no flash writes.

The corrected selector is bits 5,10. This is a specific recovered terminal
codeword, not a general change to inferred BRAM mode or routing topology.
Source, placement, routing and every other payload bit remain identical in
the intervention. The earlier register fanout repair is already in the baseline.

Baseline image:
`934cb79c37b964d77a9d37ecbe091b7c39b01209d4eba66782dd8b3f8b205e06`.
Corrected image:
`42121ea62fb06b435f1c5edfaceb9a03e68835d97d3fd349f1c44f6dc22a47c8`.
Changed payload bits: byte66456 mask128 and byte66455 mask1, both cleared.

Evidence: [audited terminal record](https://github.com/bbenchoff/AG32-Docs/blob/059637af23bec761395473f4e3f5a8b3fc06220b/docs/release05_evidence/bram_outreg0_imux_terminal1.json)
and [investigation](https://github.com/bbenchoff/AG32-Docs/blob/059637af23bec761395473f4e3f5a8b3fc06220b/docs/BRAM_ADDRESS_SELECTOR_REPAIR_20260926.md).

The two tests fail before the correction. The database-change gate rebuilt its
50 included retained images byte-identically. The eight excluded research-policy
repacks and focused checks then pass (36 tests). Integration emission reproduces
the successful two-bit correction and leaves the other three fresh BRAM test
images unchanged. No image qualification hashes have been updated or waived.
This does not qualify the complete BRAM capability matrix.
