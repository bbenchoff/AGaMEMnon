# Shared hard-input ingress placement

The placer now rejects assignments in which distinct hard-input nets both
require the same shared first-hop wire. This is a graph-theoretic necessary
condition, not a routing policy or a one-entrance-per-net restriction.

For architecturally unique or locked hard sources, pre-placement setup finds
shared first-hop wires and computes directed reachability with each wire
removed. A placed sink reachable normally but unreachable after that removal
proves its net needs the wire. Two different nets cannot both need it. The
read-only profiles use current sink locations; movable multi-site hard sources
are excluded. No routing edges, LUT logic, image bits, or emission fences change.

## Measured result

- New compiled regression: the preceding engine accepts a conflicting fixed
  placement; the new engine rejects it while accepting a legal multi-sink case.
- Original strict graph and retained regbank32 input: preceding engine fails
  HTRANS1; experimental candidate routes in 45.45 seconds.
- Ordinary strict emission and independent logical evaluation: all 168 original
  observations match, signature `85a3e86c`; byte-exact repack, zero compared-feature
  mismatches.
- L48 hardware: original oracle **3/3 PASS**, 168 observations each, zero errors;
  known-good control PASS, final reset/release. SRAM only, no image edits.
- Fresh original-RTL build through the strict CLI: 72.04 seconds, same raw,
  compressed, and routed bytes. This first build used the experimental option.
- Fresh strict build with **no option** after default enablement: 69.11 seconds,
  first HeAP seed 1, identical raw/compressed/routed artifacts. Those exact bytes
  are qualified by the three existing hardware runs, not a fourth board session.
- Experimental compiled endpoint/carry/soft-ripple suite: 176 passed, no skips
  or failures. Default-mode rerun: **178 passed, zero skips/failures**, 180.53
  seconds (JUnit). The default regression also fails on the preceding opt-in
  binary and passes on the standard implementation.

The check is standard. Setting the former `AGRV2K_SHARED_INGRESS_CHECK` experiment
variable is unnecessary and does not change behavior.

## Identities and limits

Raw image: `24c509be62235a7ce707bb8958bee4ebb91411f5e23dea54833d8e399b4adbb6`.
Routed JSON: `d191b09f1835a07862e363d94d5dfb5ac41aeea085b6baba62395a5d2901dcb9`.
Graph PIP table: `22636e6c4fc3c958fa199fc94236db41e2e53983362aca1798a1c0288da5c722`.
Default native source: `b21ad30a9cb7bb2aa4e7bad23bcbd7aeeb0aa1fa76cc359a3eb8b98bc0db5640`.
Default binary: `3afa985acce2603e16b4053624f2b5f6a731a12386293c311565d2f6a6b25dfe`.

Detailed commands, board transcripts, artifact hashes, and independent oracle
records remain in the research ledger. This result covers the tested full-word
regbank32 contract, not arbitrary designs, structural-form qualification,
physical timing sign-off, public-main promotion, or complete vendor parity.
