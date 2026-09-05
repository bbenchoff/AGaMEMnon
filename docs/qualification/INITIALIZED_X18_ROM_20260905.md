# Initialized x18 ROM admission

The initialized-memory guard admits the characterized single-port x18 ROM
mode by hardware configuration, not source names, routes, image hashes or
particular INIT contents. The existing x1 admission uses the same controls.

Scope: one X13Y4 BRAM on AGRV2KL48, Port-A width code 0, inactive Port B,
write-disabled ROM controls, default 10 MHz MCU bus clock with 8 MHz HSE,
and no experimental memory configuration. Other x1/x18 control/site modes
remain fenced. Ordinary routing, clock and bitstream validators still apply.

## Hardware evidence

The research campaign `gpt6_x18_bit_identity_matrix_20260905` tests all 512
addresses and 18 lanes with 14 bit-identity planes and their complements.
Each logical storage bit has a distinct identity across the patterns.
Three sweeps produce 84 positive passes, 42 exact opposite-pattern negative
detections and three passing controls: 172032 positive first/settled reads.
The board was reset and released; loading was SRAM-only.

The campaign was preregistered at research commit
`0d4eac40a2ef0bfbf683c6b0b66815e45dfcfa2a`; its complete hardware evidence is
retained at research commit `220fc0eabd9117fb230d937af055f2221e7bd4ec`.
The content contract SHA-256 is
`8b3536e36afe111ba0a5279a75e859adc2e225583e7dda60190ba86d75240893`.
An independent physical-bit decoder checks the intended identities before
execution; the terminal audit checks every arm/repetition and full mailbox.

These experiments qualify read-only storage mapping in the stated mode.
They do not qualify RAM writes, coupling faults, dual-port collisions, other
sites, different clock modes or general timing closure.

## Implementation verification

Semantic admission and related feature/fence checks pass 124 focused tests.
Both supported widths are tested against alternate contents and renamed cells;
write controls, live Port B, wrong clock contexts, extra memories, other sites
and malformed address shapes remain rejected.

Ordinary CLI packing reproduces all 28 witnessed matrix images and the separate
small/full-depth patterned images byte-for-byte (30 comparisons). No emitted
image is patched. This uses retained validated routes with declared INIT
contents; fresh-source and full-regression gates remain separate.
Evidence: research campaign `gpt6_x18_ordinary_admission_20260905`.
