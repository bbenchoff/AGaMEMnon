# Control-sharing selection

Ordinary uarch builds first produce the existing isolated native-SRST
candidate set.  The selector chooses that baseline by `(slice_count,
occupied_tiles)`, retaining legacy on an exact tie.  Sharing is only measured
after this isolated selection, so it never changes synthesis, carry fallback,
or the recovered-versus-legacy decision used for the comparison.

When the selected routed JSON contains an opportunity, the CLI may make up to
two independent A/B candidates from that same immutable baseline:

| Profile | Preconditions | Environment |
| --- | --- | --- |
| `mixed` | at least one native-enable group and at least one ordinary FF | `AGRV2K_MIXED_NATIVE_CONTROL=1`, `AGRV2K_DUAL_NATIVE_CONTROL=0` |
| `dual` | at least two native-enable groups | `AGRV2K_MIXED_NATIVE_CONTROL=0`, `AGRV2K_DUAL_NATIVE_CONTROL=1` |

The profiles are never combined.  Mixed sharing needs a local line for the
ordinary FF; dual sharing uses both lines for two native-enable groups.  Each
candidate receives the selected baseline's effective state, including carry
fallback, compaction state, selectively lowered enable groups, and fallback
stages.  Its output, routed JSON, policy sidecar, ownership trace, and attempt
trace directory are profile-specific.

An optional profile is bounded to three place-and-route invocations, with a
60-second limit per invocation or a smaller user `--attempt-timeout`.  This
budget applies only after the isolated baseline has completed.  It preserves
that baseline when every completed attempt is individually either a classified
placement/directed-arc failure, or an explicit route deadline; the latter is
recorded as `optional_route_budget_expired`, not as physical infeasibility.  A
deadline never authorizes an earlier unknown result.  The exact
`CARRY_GRAPH_INFEASIBLE` refusal is likewise recorded as an optional-profile
outcome and does not restart carry or data-logic fallback for the comparison.

The result keeps the isolated baseline unless a candidate is a strict
improvement in `(slice_count, occupied_tiles)`.  If mixed and dual have equal
improved metrics, mixed remains selected because it is measured first.  The
sidecar records the baseline population and an ordered result for every
profile, including options, route hash, measured metrics, and selection.

Only those bounded outcomes and the existing classified placement/routing
exhaustion are treated as candidate rejection.  A rejected mixed candidate does
not prevent a dual candidate from being measured.  Timing, policy, validation,
abort, and unknown failures propagate.  Automatic comparison is excluded for
explicit sharing controls, replay, qualified checkpoints, BRAM-write
qualification, research profiles, and builds without automatic native-SRST
selection.

This selection is a resource comparison for separately qualified compositions.
It does not claim that every design benefits, that both compositions can share
a tile together, or that routing/timing quality improves.
