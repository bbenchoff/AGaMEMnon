# Local-output placement reachability

Placement now applies the existing local-output reachability check without an
environment-variable opt-in. Rebuild the native nextpnr overlay to obtain this
behavior; updating Python source alone does not update an older native binary.
The former `AGRV2K_LOCAL_OUTPUT_REACH=1` setting is no longer required.

For a placed slice-to-slice net, the check uses the actual driver and consumer
pins, including the selected F/Q output and input index. An exhausted small
graph search rejects a pair only when the consumer cannot be reached. Searches
exceeding 4,096 wires remain optimistic. Clocks, non-slice endpoints, and unbound
neighbors are not constrained by this check. It is a necessary graph condition,
not a proof of simultaneous routability, selector compatibility, or timing.

## Supporting evidence before default integration

- Both fresh-RTL and retained-input util20 images route on the unchanged strict
  graph and pass three original-oracle L48 runs each, with a known-good control
  in each session: 1,024 transactions, zero errors, signature `0x615eea52`.
- Fresh-RTL image SHA-256:
  `bc28b6d5005b9850795f4f016e7b0f4bf41dda01c282bcf9e768e8f205e9e644`.
- Retained-input image SHA-256:
  `8a8b7e50cc01513b6401893ccc357ee11f5724fa73b2b22461adf5f1d273a836`.
- Both images repack byte-identically; their routed logical models independently
  match all 1,024 transactions. These checks alone are not silicon evidence.
- The real compiled endpoint and carry suites pass 162 tests with no skips
  under the former opt-in. The pre-integration full Windows suite at `c6a05c2`
  passes 2,176 tests with 378 skips, which are not native/hardware passes.

Research records stay in AG32-Docs under `tools/vendor_parity/`, in
`gpt6_util20_fresh_silicon_20260905`, `gpt6_util20_silicon_20260905`, and
`gpt6_local_reach_native_20260905`.

## Default-path verification

The native pin-pair regression tests both the absent variable and the legacy
opt-in. Against the old native binary, the no-variable unreachable case fails
as intended, while the other three cases pass. This proves the new regression
detects the behavior being changed, rather than merely checking source text.

Post-change compiled endpoint, carry, and soft-ripple tests pass **174 tests,
no skips**, with the option absent. A first run was interrupted by a WSL
shutdown before reporting a result; it is retained as an infrastructure
interruption, not a passing run. The complete retry uses native binary SHA-256
`f53c10ad7f5f541b74a07be018df209259b36863572b94c0efb8bd852feb5a1e`,
with source/overlay SHA-256
`ba290766f0a1bee83d6f38489df46c4ed4edb5007ceb5ab9621e3a14cef73506`.

A fresh normal strict CLI build with the variable absent succeeds in 191.64
seconds. Its routed JSON, raw image, and compressed image are byte-identical
to the witnessed fresh-RTL artifacts above. The comparison also checks the
staged silicon image bytes, three passing original-oracle mailboxes, and passing
control. No additional board session is claimed or needed for that exact-byte
qualification link. All four native attempt logs are retained for this build.
Records are `gpt6_util20_default_build_20260905/RESULT.json` and
`IDENTITY_QUALIFICATION.json` in the research repository.

The post-change full Windows suite still needs its own rerun. No default-tiered
routing safety clearance, main promotion, or vendor-parity claim follows from
this placement change.
