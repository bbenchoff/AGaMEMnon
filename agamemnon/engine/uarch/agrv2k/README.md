# `agrv2k` nextpnr microarchitecture

This directory contains the C++ Viaduct microarchitecture used by AGaMEMnon's
release place-and-route flow. It is overlaid onto a pinned upstream nextpnr
checkout and selected as:

```text
nextpnr-generic --uarch agrv2k
```

## Architecture model

The fabric graph is data, not hard-coded C++. `emit_uarch_db.py` executes the
Python architecture generator against a recording context and writes flat
device files:

| File | Contents |
|---|---|
| `dev_meta.csv` | LUT size, counts, source paths, and generation environment |
| `dev_wires.csv` | wire name, type, and coordinates |
| `dev_bels.csv` | bel name, type, coordinates, and z index |
| `dev_belpins.csv` | bel pin to wire and direction |
| `dev_pips.csv` | source, destination, type, delay, and location |

The CLI generates a release database with conduction gating, strict routing,
physical IO when requested, dedicated carry resources, and the clean-selector
gate. The C++ loader replays those records into nextpnr.

## Backend behavior

The uarch currently provides:

- LUT/LUT+FF and standalone-FF packing;
- constant packing and clock-input binding;
- exact MCU-edge lane binding;
- regional conduction-aware placement with deterministic seed variation;
- cap-controlled density and route-driven fanout splitting from the CLI;
- physical input/output endpoint packing on characterized L48 routes;
- `ALTA_BRAM9K` placement, read-only/narrow pin trimming, localized constants,
  and slot-exact dynamic input-driver binding;
- opt-in dedicated carry packing with one head seed per chain and contiguous
  same-tile placement;
- conservative LUT, FF, and carry timing arcs;
- placement replay for qualified checkpoints;
- placement legality checks for even-slot routing and pinned special blocks.

The selector/conduction-gated device graph and strict bitgen are independent
checks: a route must exist in the release graph and every configurable PIP must
have an accepted exact encoding.

## Build

`build.sh` checks out nextpnr at
`2b560ad0ccc6e7e93ad8bd6cb0f88f925bbb314b`, copies `agrv2k.cc` into the
Viaduct source tree, adds it to `generic/CMakeLists.txt`, and builds
`nextpnr-generic`. The operation is idempotent. Override `NEXTPNR` to use an
existing checkout and `NEXTPNR_PIN` to test another commit.

```bash
./agamemnon/engine/uarch/agrv2k/build.sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"
```

The script is used from MSYS2/mingw-w64 on Windows and from a normal Linux
build environment. Required tools are CMake, Git, a C++ compiler, Boost, Eigen,
and optionally Ninja. Link-time optimization is disabled because it is not
reliable on the qualified mingw toolchain.

To verify registration:

```bash
"$AGAMEMNON_UARCH_NEXTPNR" --uarch '?'
```

Normal users should invoke the backend through:

```bash
agamemnon build design.v --uarch -o design.bin
```

The CLI creates/caches the required `dev_*.csv` database and sets the backend
options consistently.

## Current boundary

The backend routes the 72-design randomized matrix and reduced hard-BRAM SERV
without a checkpoint. The silicon-qualified SERV matrix passes seven of eight
placements at cap 5 and the remaining placement at cap 4.

Dedicated carry is limited to one tile and remains opt-in. BRAM Port B is
represented and routable but is not silicon-qualified; fresh BRAM pin routes
need qualified corridor selection. Timing lacks exact native wire classes and
clock/IO/hard-block/package delay. Physical package mapping is limited to L48.
See `docs/STATUS.md` for the product support boundary.
