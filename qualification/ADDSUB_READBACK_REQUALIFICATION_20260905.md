# Add/sub readback requalification

The retained structural add/sub failure was routing-dependent, not a failure
of its logical composition. Its overflow readback used the withdrawn interior
translation `X14Y7_RMUX15 -> X14Y7_RMUX69`, pair `(0,8)`. The existing generic
selector policy already rejects that translation while retaining exact
coordinate-specific observations.

Selecting the already-driven `X15Y7_RMUX63` source with exact pair `(5,7)`
changes four configuration bits plus CRC. The repaired retained image passes
all 4,096 scheduled arithmetic observations in three controlled L48 runs,
without changing LUTs, clocks, registers, or placement.

A fresh strict placement/route through the current engine, followed by normal
emission using the explicit research requalification flag, also passes the
same 4,096 observations in three controlled runs. This image has no raw edits.

| Artifact | SHA-256 |
| --- | --- |
| Retained failing image | `35c975b0a38ed7252577c3d093f2bee6e5639bb26e2dddf7f2e422361e83deee` |
| Four-bit repair | `b4d83c0707f9bc3afee0a67b99fd69326666ed041a144fc60ba3920910c8d68f` |
| Fresh strict routed JSON | `0af3cce21e77c602140bd3e684e682e239cbb580a474f55b5304c60d9b019487` |
| Fresh normal-emitter image | `5acbcd2a7d155dccc77464381bb8f76f9096780ee51e097aeb1177d7af5eccd7` |
| Passing 4,096-byte trace | `4a89ffdd8287e2757462ba91507d7b5d4df737c85cb4198ecc11464bc1a8f730` |

Research evidence remains in AG32-Docs under
`tools/vendor_parity/gpt6_addsub_readback_repair_20260905` and
`tools/vendor_parity/gpt6_addsub_current_route_requalify_20260905`.
The investigation is `docs/GPT6_ADDSUB_OVERFLOW_BRANCH_2026-09-05.md` there.

The logic-wide add/sub fence is removed on this evidence. Both original
negative image hashes remain rejected; no other logical-design fence is
removed. Generic route restrictions remain unchanged. This does not qualify
default tiered routing, every operand, or general vendor parity. Ordinary
no-override emission reproduces the witnessed image byte-for-byte; its record
is `tools/vendor_parity/gpt6_addsub_current_route_ordinary_20260905/RESULT.json`
in AG32-Docs. The 17 focused negative-image and selector tests pass.

The placement-keystone fixture now retains both routes. Historical files and
their integrity/compiled A/B checks are unchanged; ordinary emission of the
historical checkpoint must refuse its unconnected active I3. The new
`current_seed3_routed.json` replays to the witnessed raw and compressed hashes
without an override. The combined fixture/fence/selector group passes 21 tests
with one historical compiled A/B skip; this is not a new full-suite result.
