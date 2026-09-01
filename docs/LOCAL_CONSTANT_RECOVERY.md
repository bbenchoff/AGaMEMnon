# Local constant replication (`AGRV2K_LOCAL_CONSTANTS`) — opt-in, experimental

## What it is
The default flow drives every constant consumer from one shared `$PACKER_GND` / `$PACKER_VCC` cell.
The placer pins that cell near the MCU boundary, so fabric-wide constant fan-in becomes long
cross-fabric routes. This is the dominant cause of two problems: **placement starvation** (about half
of the routability gaps stall because many cells all need to reach that one far constant) and
**silent-wrong silicon** for carry-heavy designs (the long constant routes do not carry correctly).

`AGRV2K_LOCAL_CONSTANTS=1` splits the shared constant net so every consumer past the first gets its
**own local driver cell + net** (parameters copied verbatim from the prototype), letting the
wirelength-driven placer keep each constant source adjacent to its single consumer. It also folds the
spurious constant tied to the unused `CLK` pin of combinational (`FF_USED=0`) slices, which otherwise
must route to a non-conducting tile clock mux once the placement starvation is relieved.

## Safety: opt-in, default byte-identical
The feature is reached **only** when `AGRV2K_LOCAL_CONSTANTS` is set. With it unset (the default), the
new code is unreachable and emission is **byte-identical** to before — designs that route normally are
completely unaffected, so this change carries no default regression.

## Fail-closed caveat — read before trusting an enabled build
A design that could not route with the shared constant may now **emit** with local constants. **Emission
is not a correctness claim.** As with any emitted image, a local-constant image remains subject to the
silicon-negative fence and must pass a preregistered, model-backed silicon contract before it is trusted
or counted as parity. Enabling this flag can turn a safe *refusal* into a *candidate* image that has not
yet been witnessed on silicon.

## Status
The mechanism is silicon-validated as a real fix for a bounded set of designs (arithmetic/priority
families whose escapes it corrects, plus structural starvation designs it lets emit correctly), and a
per-design lottery for others (some emit correct, some silent-wrong). Promoting it from opt-in to a
default therefore requires, per design: build with the flag, witness on silicon, qualify the correct
ones and fence the wrong ones. Until that per-design witness+fence pass is complete, this is an opt-in
research capability, not a default behavior change.
