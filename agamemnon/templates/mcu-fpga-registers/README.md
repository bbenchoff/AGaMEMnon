# MCU/FPGA registers

This project strictly replays the silicon-qualified L48
ID32/scratch16/counter3/W1C1 map and exercises it through External AHB at
`0x60000000`:

| offset | measured 32-bit behavior |
|---:|---|
| `0x0` | immutable canonical ID `0x4147414d` |
| `0x4` | reset-zero held 16-bit scratch, zero-extended |
| `0x8` | free-running three-bit counter (`0..7`), zero-extended |
| `0xc` | zero-extended one-bit qualification W1C hook: write bit 1 to set, bit 0 to clear; set wins |

The exact scratch object accepts aligned word and halfword writes and independent
byte writes at `+4`/`+5`. Its read, write, reset, coexistence, and independence
matrix was run on the L48 part. The counter and W1C hook are deliberately small
qualification features, not promised production peripherals.

```text
agamemnon build
agamemnon run --transport dap --words 12
```

The twelve result words are FCB status, reset-held ID and scratch, scratch
readbacks after word/halfword/byte writes, counter coverage, W1C set and clear
readbacks, final ID/scratch preservation, and `PASS` (`0x50415353`) or `FAIL`
(`0x4641494c`). Reset-held counter/status and counter range checks are folded
into the final verdict. The SRAM command is volatile.

`logic/top.v` and `logic/public32_exact_map_L48_routed.json` are byte-identical
copies of the source fixture and pure-open routed checkpoint behind the silicon
record. Build strictly repacks that checkpoint and verifies every pinned input
and output hash; editing either artifact fails closed. The source is a mechanical
route-replay fixture, not portable canonical RTL, and this profile does not
enable the generic decoded-only `AGAMEMNON_MCU_ENTRY` route option.

The preserved public16 profile remains available as
`l48-public16-exact-map-2026-08-15`; its source and route are retained as
`logic/public16_exact_map.v` and `logic/public16_exact_map_L48_routed.json`.
The former one-byte scratch profile remains available as
`l48-complete-byte-waited-2026-08-05`; its source and route are retained as
`logic/complete_byte_waited8.v` and `logic/id_scratch8_L48_routed.json`.

This is an exact L48, HSE=8, SYSCLK=10 profile. Raw `HRDATA[31:16]` is measured
for all four registers; software does not mask word reads. Signed or misaligned
accesses, every unexercised foreign subword offset, bursts/full-window decode,
production status-set ingress, a generic register-bank generator, arbitrary
placement/width, and other packages/devices are not qualified. Hard
`MCU_RESETN` and HRESP error responses also remain unqualified.
