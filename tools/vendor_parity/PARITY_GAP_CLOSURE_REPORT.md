# Parity-gap closure worklog

This worklog records desk-side changes against the frozen vendor-parity
frontier. A routed image is not a silicon result, and a passing unit or
byte-identity gate is not a claim of broad vendor parity.

## D0: hermetic nextpnr build and router2 reservation probe

Status: desk-qualified for commit; no board claim.

The release build now applies the Viaduct timing hooks and the two router2
reservation corrections from checked-in patch files to the pinned upstream
nextpnr revision. It also builds a synthetic microarchitecture used only for a
mandatory process-boundary capability probe. The probe deliberately creates a
satisfiable case in which a high-fanout constant net is inserted first and a
signal net needs the shared choke resource. A qualifying executable must route
the signal through that choke and the constant through its local source.

The corrections are intentionally narrow:

- consolidated packer constant nets are not given irrevocable heuristic
  pre-reservations; their actual routes still pass through normal availability
  and negotiated-congestion checks;
- when two different nets collide in heuristic pre-reservation, neither wins
  by processing order. The resource is returned to normal negotiated
  congestion for that run;
- the dead `NEXTPNR_ROUTER2_STAGNATION_LIMIT` setting was removed. There is no
  runtime claim that stock router2 honors a private stagnation-limit knob.

Reproduction and negative control:

- a linked clean checkout at pinned nextpnr revision `2b560ad0` was built
  through `agamemnon/engine/uarch/agrv2k/build.sh`;
- a second invocation was idempotent: both patches and both microarchitecture
  registrations were detected as already present;
- with both patches, the synthetic fixture routed `SIG` through `CHOKE` and
  the constant net through `LOCAL_GND`;
- after reversing only the reservation patch and rebuilding, stock router2
  failed the otherwise satisfiable signal arc; reapplying the patch restored
  the passing result.

Gates run on 2026-08-26:

| Gate | Result |
|---|---|
| Focused hermetic/probe tests | 73 passed |
| Qualified pack regression / byte-identity set | 59 passed |
| Full Python suite | 1526 passed, 46 skipped |
| `addsub16` user-form canary | Routed desk image after the existing LUT-carry fallback; timing and strict bitgen checks passed |
| `regbank16` user-form canary | No image after 40 attempts; every attempt stopped at post-placement fixed-input conduction legality before routing |

The `regbank16` result retains the already documented no-image frontier; it is
not a newly introduced failure and no routing conclusion follows from a
placement-stage rejection. The `addsub16` result is useful desk evidence but
has not been run on silicon in this change and therefore does not close a
parity item.

## D1: preserve direction in placement use of the routing graph

Status: desk-qualified for commit; no board claim.

The admitted routing-resource graph is directed. Three placement paths had
been treating a witnessed tile edge as if it also proved the reverse edge:

- the exact conduction-aware embedder accepted either orientation;
- CONDPAIR checked candidate/neighbor pairs without distinguishing driver from
  user, and its optional K-hop closure inserted reverse edges;
- regional dependency scoring tested an already placed consumer in the wrong
  direction, while regional candidate ordering first built an undirected copy
  of the graph.

The exact embedder now requires producer-to-consumer reachability and uses a
separate predecessor index only when placing an upstream producer beside an
already placed consumer. CONDPAIR checks an already placed driver toward the
candidate and the candidate toward an already placed user. K-hop reachability
follows outgoing edges only. Regional placement keeps its capacity-complete
candidate set without manufacturing reverse edges, and its dependency score
uses the net direction.

Gates run on 2026-08-26:

| Gate | Result |
|---|---|
| C++ compile in existing overlay build | Passed |
| Focused directed/placement/MCU tests | 94 passed |
| Qualified pack regression / byte-identity set | 59 passed |
| Fresh pinned-tree build through `build.sh` | Passed; mandatory reservation fixture also passed |
| Full Python suite | 1529 passed, 46 skipped |
| `addsub16` user-form canary | Routed release-strict desk image after LUT-carry fallback at cap 2 / seed 4; timing passed at 10 MHz; 0 unmapped selectors |
| `regbank16` user-form canary | Retained known no-image boundary: 40/40 attempts stopped at the same post-placement fixed-input reachability rejection before routing |

The addsub result is a desk routing improvement only. The regbank result does
not show a router failure because router2 was never entered, and neither result
is a new silicon qualification.
