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
- qualified-checkpoint placement replay;
- placement legality checks for special blocks and routing constraints.

The graph and bitgen are independent checks. A route must be present in the
filtered graph and every configurable PIP must have an accepted strict
encoding.

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
unqualified-package warning. BRAM hardware support is limited to the qualified
x18 Port-A path and x2 Port-B read/control path. Carry beyond the qualified
same-tile footprints and 33-site corridor fails closed. Timing uses
conservative mux-family delays rather than exact native wire classes and does
not model clock skew, IO, hard-block, or package delay.

See [docs/STATUS.md](../../../../docs/STATUS.md) for the complete product
support matrix.
