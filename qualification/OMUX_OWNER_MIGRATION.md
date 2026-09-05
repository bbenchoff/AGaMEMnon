# OMUX owner-based emission migration

The 2026-09-04 output-owner correction changes 16 of the 58 retained packed
images. The remaining 42 images are unchanged. This is a deliberate,
silicon-backed image migration, not byte-neutral routing promotion.

`omux_owner_requalification_20260904.json` binds each changed routed artifact,
old and new raw image hashes, exact build environment, immutable research
report URL and canonical-LF report hash. Each changed image has three passing
silicon runs with a passing control. Control roles remain controls; they are
not advertised as production functionality. No package, timing, or bus scope
is widened.

The pack registry, exact legacy clock-quarantine image hashes, five SDK image
profiles, and image claim constants move together. Routed checkpoints, clock
leaf sets and owners, RTL sources, and build environments are unchanged.
The research-data inventory must also bind the new quarantine file.

Historical evidence ledgers, checkers, oracle sources, and hardware runners
remain intact. Their embedded image hashes describe those historical trials,
not the current emitter. SDK profiles retain `previous_evidence` links and
point their current `evidence` links to the new manifest. The public16/public32
and status tests use the separately versioned sampling-v2 oracles described in
`PUBLIC_MAP_SAMPLING_V2.md`; the original fixed-cadence failures remain recorded.

The immutable bench control remains the original public32 image. Changing the
SDK's current public32 image does not authorize substituting it for that
control or changing the control harness's hash pins.

Verification must include both D0 Rule 2's 50 release-policy artifacts and the
eight research-policy artifacts that Rule 2 deliberately excludes. A passing
Rule 2 run alone is not a 58-artifact result. The broader SDK, packaging,
clock-validation, and policy tests remain required before promotion.
