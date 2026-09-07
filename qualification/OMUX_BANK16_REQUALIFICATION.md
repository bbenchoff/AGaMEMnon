# Bank16 OMUX-owner requalification, 2026-09-04

Four corrected retained images each match their original SRAM oracle contract
on L48 three times. Every session first passes the unchanged public32 control,
then ends with reset and lock release, without flash writes. No Pico changes.
These are exact retained low16 profiles, not arbitrary placement or upper-lane
qualification. No image, SDK, clock-quarantine, or fingerprint pin is updated.

| Profile | Corrected image SHA256 | Original contract |
| --- | --- | --- |
| word/byte waited | `91544cf6f44149e1c20592505d3627a18b8c98642fec7c96fbf0bd2a4f93ec2e` | 100 patterns, all write/isolation/reset errors zero |
| word/byte/halfword waited | `2ef372f50ff2825e63104837e2a838f68c5ce5a934dc5fc02b296cfbff50a51a` | 100 patterns, all word/subword/isolation/reset errors zero |
| read-word0 gated | `7306e3f086ad6967bbdaaca3b44897c500aae38b60e20bcc98bf1bb504a1fb2a` | 64 patterns, read mask1, all ten error groups and reset values zero |
| public scratch+4 | `3445e530006915af7d5f70bbf568638b36eb44c0916ce52baebb3a4b18809867` | 32 patterns,160 observations, all16 error groups zero |

All four oracle source hashes match historical evidence. Halfword and scratch+4
rebuilt firmware also match historical stub hashes. The other two historical
records did not contain a stub hash: their firmware is explicitly recorded as
a fresh build of unchanged, hash-matching source, not claimed byte-identical
to an unavailable historical binary. The runner independently rebuilds each
and verifies entry, absence of undefined symbols, size, and explicit hashes.

Scratch+4 mailbox words19..23 are diagnostic in the original contract, not
universal expected values. They are retained in full; all three runs observed
upper AND/OR=`ffff/ffff` and raw/LBU/LHU diagnostic samples=`ffff8001`.
This does not qualify upper read lanes. Every constrained mailbox word and
completion sentinel is checked; mutation tests cover each required word and
reject missing/extra mailbox data.

Research evidence: AG32-Docs
`tools/vendor_parity/gpt6_bank_omux_silicon_20260904`, including source/image
staging, original controls, all board logs and independent `ANALYSIS.json`.
The full16-image OMUX migration now has five rows left to account for: two
status overlays, carry seam, and two SERV cases. Do not rebaseline those on
the strength of these four passes.
