# Single-source BRAM AddressA[9] terminal — September 5, 2026

For X14Y4_RMUX54 -> X13Y4_IMUX03, the old exact word selected CFG_IMUX0
indices 42,43,45. A ground-only x18 observation had not isolated its sources.
With independent full-depth ROM address inputs, that word produces A9 AND A11.

On one fixed routed ROM8192 composition, three one-bit-controlled arms give:

| Selected indices | Complete silicon result, three repetitions each |
| --- | --- |
| 42,43,45 | A9 AND A11 alias: 2,032 erroneous visits, signature dffd9633 |
| 43,45 | A9:=A11 alias: 4,100 erroneous visits, signature 71f6ce75 |
| 42,45 | Correct A9: zero errors, signature 092f7a0f |

All predictions were committed before the experiment. Each repetition visits
all 8,192 addresses sequentially and in a permutation, checking first and
settled reads: 32,768 reads per repetition. All public32 controls pass; the
zero-INIT negatives match their complete independent predictions. The final
reset and released board lock are recorded. SRAM only, no flash writes.

The corrected image is
`690f3f73ea50ebf34abb81d33843d8d5c18620cd8152d26cee30baff543235ba`.
It differs from the failed image by just file byte 66231 mask 0x10 cleared,
plus CRC. The reciprocal control clears file byte 66115 mask 0x10 instead.

Evidence: [AG32-Docs, pinned terminal campaign](https://github.com/bbenchoff/AG32-Docs/tree/8a5dfa98403cff71e0916f731a558df1186c51cd/tools/vendor_parity/gpt6_bram8192_address9_terminal_20260905).
The pre-registration is retained at commit `ec2aa94d0247857dd621f1e2be88d086750583e5`.

The exact boundary override and the most-specific L0 resolver tuple now select
only 42,45 (local 6,9). The historical table filename is retained for
compatibility, but this row's evidence points here. The other row is unchanged.
Coarser L1/L2 classes are not generalized from this one terminal experiment.

This does not make the full-depth design an ordinary fresh-source build: the
probe still has explicit two-stage address buffers, a private graph-derived
A5 detour outside the native search rectangle, and restored INIT. Automatic
buffering/allocation, memory admission, other terminals/sites/widths and
write/collision semantics remain separate work.

Ordinary emission on the unchanged routed input, followed only by original
INIT restoration, reproduces the witnessed passing image byte-for-byte. The
initial two table tests fail before correction. After correction, the automatic
fingerprint escalation rebuilds its 50 included images byte-identically
(208.96 seconds), then correctly refuses the stale fingerprint. After reviewing
and updating that pin, focused checks plus the eight excluded-policy repacks
pass **127**, with one missing-Yosys skip; that skipped test passes separately
under configured WSL Yosys (1.75 seconds). Thus all 58 retained images are
repacked without any image-pin changes. These are not a fresh full-suite result.

The reproduction and XML evidence are in AG32-Docs under
`gpt6_bram8192_ordinary_terminal_emitter_20260905` and the terminal campaign.
