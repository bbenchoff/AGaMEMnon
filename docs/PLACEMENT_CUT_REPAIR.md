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
The incoming and relocated cells must both pass architecture legality before
the pair is committed. Failed trials restore the competing cell to its exact
previous BEL and strength. At most 64 alternative sites are tested per
incoming placement candidate. Locked, stronger, clustered, and non-solver
cells are not relocated. A failed search leaves ordinary HeAP search in charge.

The earlier displacement-only experiment requeued the competing cell and
could alternate indefinitely between two owners until HeAP's iteration limit.
The current pair search retains a complete legal location for both cells;
it does not requeue a displaced cell without a destination.

This is a necessary-resource placement heuristic. It does not prove full
routability or timing, and it does not handle arbitrary multi-cell or cluster
relocation. Existing bitstream and silicon admission gates remain in force.
