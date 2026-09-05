# Public-map sampling oracle v2

The versioned `mcu_ahb_public{16,32}_sampling_v2_test.c` oracles retain every
functional assertion and mailbox field of the historical exact-map tests.
Only counter sampling changes: 2048 reads instead of 512, with deterministic
xorshift-varying 0..31 delay iterations instead of repeating 0..7 delays.
Full eight-state coverage remains mandatory. Tests reverse just these changes
and require exact equality to the historical source, plus new source hashes.

The original test sources, their evidence records, and control firmware hashes
remain intact. These are explicit versioned qualification inputs, not a silent
replacement of the historical control or a relaxation of image admission.

On L48, original and corrected public16 and public32 images each passed the
complete v2 oracle three times. Each of the four sessions first passed the
original hash-bound public32 control; all ended with reset and lock release,
without flash writes. These are bounded observations, not a general reliability
guarantee. Earlier fixed-cadence coverage failures remain retained.

| Profile | Original image SHA256 | Corrected image SHA256 |
| --- | --- | --- |
| public16 | `3fd36e5b3a7f79c6da195315921658e44343513de9a85960c99e3cf638aff481` | `8ff75e361815bf7fc8d6b96deb691b5dd20af1dea35e7556709b5ba54a5a11bb` |
| public32 | `ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5` | `e32d5a15f3cdf5d2050a5ea2fb5d2a7e90515694540ea03bbb37f89179ecdd29` |

Firmware SHA256: public16
`d2090b74ebb3157653039f1a2e8350c47a9b334d3c05958af75031b250641ac9`;
public32 `33e5827ea8f7381a24b0fecd4d54b24ecd413b93e4d37240377f1314317e7a45`.

Research evidence is retained in AG32-Docs under
`tools/vendor_parity/gpt6_full_sampling_{old,new}_public{16,32}_20260904`,
including original controls, staged inputs, complete mailboxes, and board logs.
Raw cadence-discriminator evidence is `gpt6_counter_sampling_silicon_20260904`.
Public16 still qualifies low16 read data only; public32 checks full32 values.

Remaining integration: migrate only witnessed image/SDK/admission pins with
their evidence, and make version selection explicit in the normal qualification
workflow. Do not replace all changed corpus hashes on this evidence.
