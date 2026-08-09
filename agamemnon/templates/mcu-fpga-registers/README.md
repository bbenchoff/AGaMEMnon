# MCU/FPGA registers

This project strictly replays the silicon-qualified L48 ID/scratch fabric
profile and exercises it through External AHB at `0x60000000`:

- offset `0x0` returns immutable ID byte `0x4d`;
- offset `0x4` is a reset-zero writable scratch byte.

```text
agamemnon build
agamemnon run --transport dap --words 8
```

The eight result words are FCB status, ID, reset scratch, readbacks of writes
`0x5a` and `0xa5`, ID after an ignored write, preserved scratch, and `PASS`
(`0x50415353`) or `FAIL` (`0x4641494c`). The SRAM command is volatile.

`logic/top.v` is the exact public source. `logic/id_scratch8_L48_routed.json`
is the same pure-open route used by the retained silicon record, with only an
absolute checkout prefix removed from diagnostic `src` annotations. Build
strictly repacks that route and verifies every pinned input/output hash. Editing
either artifact fails closed. This exact profile does not enable or promote
the generic decoded-only `AGAMEMNON_MCU_ENTRY` route option.
