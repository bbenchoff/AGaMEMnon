# MCU/FPGA registers

This project strictly replays the silicon-qualified L48 complete-byte waited
register-bank profile and exercises it through External AHB at `0x60000000`:

- offset `0x0` returns immutable ID byte `0x4d`;
- offset `0x4` is a reset-zero writable scratch byte;
- writes complete with exactly one controlled wait; reads remain zero-wait.

```text
agamemnon build
agamemnon run --transport dap --words 8
```

The eight result words are FCB status, ID, reset scratch, readbacks of writes
`0x5a` and `0xa5`, ID after an ignored write, preserved scratch, and `PASS`
(`0x50415353`) or `FAIL` (`0x4641494c`). The SRAM command is volatile.

`logic/top.v` is the exact public source. `logic/id_scratch8_L48_routed.json`
is the same pure-open route used by the retained silicon record, with only LF
canonicalization and an absolute checkout prefix removed from diagnostic
`src` annotations. Build
strictly repacks that route and verifies every pinned input/output hash. Editing
either artifact fails closed. This exact profile does not enable or promote
the generic decoded-only `AGAMEMNON_MCU_ENTRY` route option.

The qualified boundary of this replayed image is aligned single-word writes
to this register bank; it instantiates only `HRDATA[7:0]`, so upper read
lanes float high here. Exact zero-extended word reads, aligned byte/halfword
semantics, and non-SINGLE burst rejection are separately qualified in
[the register-bank ledger](../../../docs/MCU_AHB_REGISTER_BANK.md) but are
not part of this exact replayed profile; hard `MCU_RESETN` and HRESP error
responses remain unqualified everywhere.
