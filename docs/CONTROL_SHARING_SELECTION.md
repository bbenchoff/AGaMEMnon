# Automatic control-sharing candidate

Development status: implemented on the control-selection branch, awaiting
fresh ordinary-source builds, retained-image regression and qualification.
This document does not declare a new supported default on main.

The implementation first completes the existing isolated native-reset mapping
comparison. It inspects the selected routed registers and tries at most one
additional composition: mixed native/ordinary sharing when both populations
exist, otherwise dual-native sharing when there are multiple enable groups.
The two options are not enabled together. Designs without an opportunity do
not incur another build. Explicit sharing options and replay, qualified and
research flows retain their policy.

The alternative must complete routing and emission and improve the pair
`(slice count, occupied logic tiles)`. Isolated wins ties. Missing placement
information cannot produce a favorable tile count. A classified placement or
routing exhaustion retains the completed baseline; policy, timing, timeout
and unknown failures are not silently converted to success. Candidate products
and requested reports use private destinations until selection.

The existing native-SRST selection sidecar records the composition options,
population, result and selected profile. Equal-slice SRST mappings now prefer
fewer occupied tiles, retaining legacy on an exact resource tie. This avoids multiplying both synthesis mappings by every sharing
profile, while addressing the measured case where sharing routed successfully
but increased tile count.

Remaining validation includes exact option propagation, candidate synthesis
and carry-fallback identity, private-report isolation, the 58 retained images,
and fresh builds of the mixed fixture and the width workloads. The existing
96-slice, ten-versus-nine-tile silicon comparison motivates this work but does
not itself qualify this automatic selection implementation.
