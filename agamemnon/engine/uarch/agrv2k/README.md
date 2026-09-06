# `agrv2k` nextpnr backend

This directory contains AGaMEMnon's C++ Viaduct microarchitecture for
nextpnr-generic:

```text
nextpnr-generic --uarch agrv2k
```

Normal users select it through `agamemnon build --uarch`.

## Device model

The architecture graph is generated from the packaged chip database rather
than hard-coded in C++. `emit_uarch_db.py` records the active Python model as:

| File | Contents |
|---|---|
| `dev_meta.csv` | architecture and generation metadata |
| `dev_wires.csv` | wire names, types, and coordinates |
| `dev_bels.csv` | bel names, types, coordinates, and z values |
| `dev_belpins.csv` | bel pin connections and direction |
| `dev_pips.csv` | routed edges, types, delays, and locations |

The CLI applies package selection, conduction gating, clean-selector gating,
requested IO/MCU resources, supported BRAM corridors, and optional carry
resources before the C++ backend loads the graph.

## Backend features

- LUT/LUT+FF and standalone-FF packing;
- constants and global-clock binding;
- exact MCU read/write lane binding;
- connectivity-aware regional placement;
- density retry and route-driven fanout splitting;
- package-specific L100, L64, L48, and Q32 input/output packing, with L48
  silicon-qualified and the other maps explicitly unqualified;
- `ALTA_BRAM9K` packing, pin trimming, constants, and slot-exact dynamic
  driver binding for the supported Port-A/Port-B paths;
- opt-in same-tile carry placement and one qualified 33-site corridor for a
  seed plus up to 32 arithmetic stages;
- conservative LUT, flip-flop, and carry timing, with certified exact local
  wire timing where the hash-pinned table has a normalized pair and the
  conservative source-family fallback everywhere else;
- fail-closed registered-profile route replay after exact source/checkpoint
  hashes, post-Qin primitive/parameter/port/graph verification, pinned clocks
  and final raw/compressed image hashes;
- placement legality checks for special blocks and routing constraints.

The graph and bitgen are independent checks. A route must be present in the
filtered graph and every configurable PIP must have an accepted strict
encoding.

`--qualified-checkpoint PROFILE` does not accept a routed-JSON path and does not
ask nextpnr to rediscover a dense qualified route. For `build`, the profile
registry admits only the exact +0 and +4 bank16 structural fixtures and
checkpoints; four additional hash-bound `bram-tmux9-*` profiles are
retained-checkpoint pack-only (`agamemnon pack --qualified-checkpoint`) and
back the `--qualified-bram-write` fresh source-to-route path. It pins
source/checkpoint hashes, HSE=8, SYSCLK=10, packaged data, strict build options,
and expected raw/compressed hashes; ambient experimental switches fail before
synthesis. Exact replay proves the synthesized source is logically isomorphic,
copies each BEL and per-net `ROUTING` attribute, and invokes strict bitgen. Any
functional change needs a separately reviewed profile and silicon evidence.

## Build nextpnr

`build.sh` checks out nextpnr commit
`2b560ad0ccc6e7e93ad8bd6cb0f88f925bbb314b`, installs `agrv2k.cc` into the
Viaduct source tree, registers it with CMake, and builds `nextpnr-generic`.
The operation is idempotent.

```bash
./agamemnon/engine/uarch/agrv2k/build.sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"
```

Set `NEXTPNR` to use an existing checkout or `NEXTPNR_PIN` to test another
commit. Required build dependencies are Git, CMake, a C++ compiler, Boost,
Eigen, and optionally Ninja. Link-time optimization is disabled for reliable
MinGW builds.

On Windows, set `AGAMEMNON_UARCH_NEXTPNR_RUNTIME` if the executable requires
DLLs from its own MSYS2/MinGW runtime directory. AGaMEMnon keeps OSS CAD Suite
libraries out of the native nextpnr process and runs a loader preflight before
routing.

Verify backend registration:

```bash
"$AGAMEMNON_UARCH_NEXTPNR" --uarch '?'
```

Build a design:

```bash
agamemnon build design.v --uarch -o design.bin
```

## Supported boundary

Physical package maps ship for L100, L64, L48, and Q32. L48 is independently
cross-checked and silicon-qualified; the other three are recovered from
architecture metadata and every physical PCF build using them emits an
unqualified-package warning. BRAM hardware support covers the
qualified X13Y4 x18/x9 Port-A and x2 Port-B read/control subsets, the opt-in
exact site-read profile (fresh full-depth x18 at X13Y3/X13Y4), and the four
hash-bound fixed-address registered-source write profiles; everything else
fails closed. Carry beyond the qualified
same-tile footprints and 33-site corridor fails closed. Timing uses
conservative mux-family delays rather than exact native wire classes and does
not model clock skew, IO, hard-block, or package delay.

See [docs/STATUS.md](../../../../docs/STATUS.md) for the complete product
support matrix.

## Experimental placement analysis

The default logic-pair legality check now caches exact graph reachability in
compact bitsets. It rejects disconnected pairs even for sources with large
reachable components. Connectivity alone does not establish simultaneous
routability or silicon correctness.

The experimental branch provides these native-only opt-ins for placement
research. They are not qualified release configurations:

- `AGRV2K_HEAP_CONSTRAINT_ORDER=1` prioritizes cells with smaller conservative
  fixed-endpoint/region domains through the Viaduct HeAP configuration hook.
- `AGRV2K_LOGIC_DOMINATORS=1` computes exact single-wire dominators for logic
  output roots and rejects distinct nets that necessarily require one wire.
  It disables parallel HeAP refinement to serialize placement transactions.
- `AGRV2K_AUDIT_DOMINATOR_CACHE=1`, together with the dominator option, checks
  incremental ownership against full recomputation at every validity query.
  This diagnostic can substantially increase placement time.
- `AGRV2K_HEAP_RETAIN_BEST=1` restores an earlier complete HeAP solution if
  later legalization exhausts its search, then runs the normal final checks.
  It does not recover unrelated errors or supply a solution when none exists.
- `AGRV2K_HEAP_REFINEMENT_BUDGET=<positive integer>`, with retain-best enabled,
  bounds cell legalization events in each later pass. It leaves the search for
  the first complete solution unchanged. Omitting it retains existing limits.
  This controls optimization work, not architectural legality or qualification.

These checks preserve the existing architecture legality gates and do not
prove complete routability, timing closure, or silicon correctness. Dominator
storage with the full native wire inventory is approximately 437 MiB in addition to the other
graph and placement data. Use the compiled native regression tests and fresh
source builds when evaluating an implementation change.

For routing diagnostics, native nextpnr accepts `--router2-heatmap <prefix>`.
Alongside the upstream aggregate heatmaps, the ownership overlay writes
`<prefix>_congested_wire_owners_<iteration>.csv`, with quoted wire and net
names, total wire occupancy, and the incoming pip for each competing net.
An empty pip denotes a source wire. `<prefix>_endpoints.csv` also records each
net's actual source and sink wires once routing setup completes, allowing
graph analysis to use the exact placement of that run.
`<prefix>_wire_restrictions.csv` records reserved and unavailable wires after
reservation setup. Every 25 iterations, `<prefix>_occupied_wire_owners_<iteration>.csv`
captures all internal occupied wires, including those with only one owner.
These snapshots allow analysis of competing paths against ordinary occupancy.
Ownership export happens after routing workers
finish and does not modify routing state. Without the heatmap option there
is no export. This records observed contention, not unavoidable graph cuts
or physical configuration correctness; long runs can produce many files.

`NEXTPNR_ROUTER2_REROUTE_INTERVAL=<1..1000000>` enables an experimental
coordinated rerouting pass after each specified number of iterations, only
while wire or configuration-resource congestion remains. It releases routed
arcs on nets with no architecture-bound wires, requeues those nets together,
and retains congestion history. Nets with any existing architecture binding
and individual pre-routed arcs are excluded. The ordinary route and final
legality checks still apply. Omit the variable to preserve existing behavior.
This is an opt-in experiment, not established width or timing closure.
