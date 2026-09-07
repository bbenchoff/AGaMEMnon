# L48 SPI receive qualification

Work-branch implementation `43eb36f` admits the corrected typed SPI0/SPI1
MISO paths. This is not a promotion of the work branch to public main/release.

The shared PIN17 enable is payload byte 92, mask `0x40` (file byte 100).
Both controllers request it through the physical-I/O owner; their distinct
receive sink routes remain separate. Missing physical bindings and known-bad
image hashes still refuse. No benchmark-name whitelist or image patch is used.

## Proven behavior

On L48, each controller passed three repetitions per ordinary-Verilog and
structural source form, with 32 transactions per repetition: mode 3, divider
256, command `A5`, four-byte response `12 34 56 78`. Vendor references passed
and retained bad images reproduced stuck-high reads. Three full board controls
and final target reset/Pico restoration passed; AG32 loads were SRAM-only.

Normal CLI packing and four fresh `--uarch --release-strict` source builds
reproduce the silicon-tested images exactly:

- SPI0: `48f856912b34b97e2aaad2fe51061172a5b811e1d6268d0e41870ac77e8d339f`
- SPI1: `f9f5c76295f3a39ffe8e8a793c161d3d1f8a1fe6768daba10af22c1f449ffde3`

Complete Windows regression on the admission revision: 2335 passed, 554
skipped, zero failures/errors; checkout clean before and after. Research
evidence is retained separately in AG32-Docs at commit `1cab093ff`, under
`tools/vendor_parity/gpt6_spi_admission_banking_20260905/RESULT.json`.

## Remaining coverage

This fixed-response contract does not prove arbitrary response patterns,
receive lengths, other modes/rates, simultaneous controllers, dual/quad,
DMA/poll/interrupt operation, alternate pads/packages or PVT margins. Older
vendor-reference receive-width observations establish byte ordering only in
their recorded scope; they do not expand this new open-image qualification.

The four corpus rows are banked successes. Broader SPI and whole-toolchain
vendor parity remain ongoing work.
