# Experimental shared-cut placement repair

`AGRV2K_HEAP_CUT_REPAIR=1` enables a bounded two-cell relocation during HeAP
legalization. It is disabled by default. The candidate is research work, not
a qualified width or routability improvement.

The architecture identifies distinct logical nets requiring a common
capacity-one logic-input entry wire in the loaded graph. These checks derive
from graph reachability, not a list of design names or coordinates. When a
trial placement conflicts, the legalizer considers movable drivers and sinks
associated with those competing owners.

For a weak, unclustered competing cell, it searches available sites of the
same BEL type, in distance order, respecting region and control-set filters.
When an otherwise legal destination has an occupant, the same bounded free-site
search first tries to relocate that occupant instead of requeueing it. Failed
occupant searches retain the ordinary legalizer fallback. Intrinsically invalid
incoming shapes do not trigger remote-conflict repair.
The incoming and relocated cells must both pass architecture legality before
the pair is committed. Failed trials restore the competing cell to its exact
previous BEL and strength. A cheap architecture predicate rejects sites
that violate existing slice-shape rules before expensive reachability checks.
It runs after provisional binding to preserve binding-dependent exceptions.
At most 64 shape-admitted alternative sites receive full legality checks per
incoming placement candidate. Locked, stronger, clustered, and non-solver
cells are not relocated. A failed search leaves ordinary HeAP search in charge.

The earlier displacement-only experiment requeued the competing cell and
could alternate indefinitely between two owners until HeAP's iteration limit.
The current pair search retains a complete legal location for both cells;
it does not requeue a displaced cell without a destination.

This is a necessary-resource placement heuristic. It does not prove full
routability or timing, and it does not handle arbitrary multi-cell or cluster
relocation. Existing bitstream and silicon admission gates remain in force.

One retained density placement replay now completes with this experiment;
that result alone does not establish routing, fresh-source emission, or silicon
correctness. Full release admission remains separate.

`AGRV2K_ENTRY_SET_CAPACITY=1` additionally checks source-aware sets of input
predecessor wires. It rejects a placement only when exact graph reachability
shows that more distinct nets must cross a set than that set has wires.
Repeated sinks of one net count as one owner. The check is necessary, not
sufficient for routing; it does not replace routed-image or silicon gates.
Its conflicting drivers and sinks feed the same bounded relocation search.
This extension is experimental and remains disabled by default.

The experimental legalizer also records committed occupant evictions. Until a
displaced unclustered cell is placed, it cannot evict its last displacer. The
history resets between legalization passes. This prevents an immediate reverse
eviction from undoing the preceding move; it neither admits an illegal site
nor establishes completeness of the bounded search.

The entry-set checker caches forward reachability as dense bit vectors. Its
optional `AGRV2K_AUDIT_ENTRY_REACH=1` diagnostic compares each newly computed
vector with the existing hash-set traversal, checking both cardinality and
membership. The diagnostic intentionally retains both representations and is
unsuitable for measuring the compact cache's memory use. The 21 focused native
legality tests pass with this diagnostic enabled. A retained 472-cell fixed
placement remains accepted with all BEL assignments unchanged; this is not a
fresh routing or silicon qualification result.
