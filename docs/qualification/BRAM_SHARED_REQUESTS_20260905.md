# BRAM shared requests and legal output bridges

The native allocator now permits a shared-net request to negotiate space from
recorded single-sink generic branches. A multi-sink owner is never an eviction
victim. Existing same-net prefixes, exact paths, source roots, and mandatory
BRAM input/output resources retain their protection.

Saved address paths are validated before any binding. An occupied path falls
back to graph allocation without leaving a partially bound prefix. Missing
edges and discontinuities encountered in the saved path retain explicit
integrity errors.

Automatic identity-buffer placement now probes the ordinary native BEL legality
predicate, not just graph reachability and vacancy. Trial bindings are undone;
if no legal site exists, the original connection is restored and provisional
objects removed. This does not exempt odd slots from qualification rules.

Research replay of unchanged synthesized full-word ROM inputs at widths 2, 4,
9 and 18 completes native routing. Previously, the first three fail packing.
This is not fresh end-to-end emission or hardware qualification of these new
routes. Initialized-memory admission, graph tables, and output truth functions
are unchanged. Correction: the initialized-read fence covers unqualified x1
and x18 modes; the existing policy admits x2/x4/x9. It is not a blanket fence
on every wider mode.

Regression coverage includes renamed-memory fixtures, source/consumer
preservation, identity truth tables, shared-tree eviction refusal, safe
single-sink displacement by a shared requester, and real native placement
legality. In particular, the formerly failing shared requester is required to
retain both consumers and the source of the displaced branch. A generic
expectation that every shared request must fail is not a safety invariant.

Integrated checks: 42 native tests passed; the Windows BRAM selection passed
195 tests with 134 skips. The complete post-change regression is separate and
must not be inferred from those focused results.

The complete Windows regression on `edac27d` subsequently passed: 2265 passed,
512 skipped, zero failures. The checkout remained unchanged throughout.

Fresh ordinary strict CLI builds of the 16-word x2/x4/x9 probes emit without
image edits. Each image then passed three control-first L48 repetitions, with
three exact zero-content negative detections per width. Both first and settled
reads match over sequential and permuted access: 192 positive observations per
width. All nine controls passed; sessions reset/released the board, SRAM only.

Witnessed raw-image SHA-256 values:

- x2: `bf221fd621451b15c4abb28f09557e3a47fcdbfbe34426d04cf5aa0950f1a627`
- x4: `8c783bdcdbfbd946e3254501bebd8d4ad5d3f699140bf9f0e51d552acf071200`
- x9: `1037bd1a95a4fa98241810ef3e0d31e49efc256d114eee8f2d01c3f94f78e29e`

This is bounded single-site, 16-word, read-only qualification. Full-depth x4
currently fails routing on a destination-dependent MCU entry conflict; RAM
writes, dual-port behavior, broader contents/sites and timing remain open.
