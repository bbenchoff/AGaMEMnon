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
are unchanged. Wider initialized modes remain fenced pending qualification.

Regression coverage includes renamed-memory fixtures, source/consumer
preservation, identity truth tables, shared-tree eviction refusal, safe
single-sink displacement by a shared requester, and real native placement
legality. In particular, the formerly failing shared requester is required to
retain both consumers and the source of the displaced branch. A generic
expectation that every shared request must fail is not a safety invariant.

Integrated checks: 42 native tests passed; the Windows BRAM selection passed
195 tests with 134 skips. The complete post-change regression is separate and
must not be inferred from those focused results.
