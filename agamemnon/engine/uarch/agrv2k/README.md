# `agrv2k` — nextpnr Viaduct microarchitecture for the AGRV2K eFPGA

This directory holds the **C++ source of our own nextpnr uarch** (`agrv2k`). It is the place/route
"brain" that nextpnr-generic lacks for this fabric: a per-pip conduction gate, a real placement
legality predicate (dense-packing rules + exit-lane reachability), and clustering. It replaces the
Python `--pre-pack arch.py` + `--pre-place` hook scaffolds we've been shipping.

## Repo model (decided 2026-07-08)

AGaMEMnon is the tool and **owns this source**. nextpnr is a *pinned git submodule* (pristine
upstream). This uarch is an **overlay, not a fork**: the build step copies `agrv2k/*.cc` into the
submodule's `generic/viaduct/agrv2k/` and applies a one-line patch to `generic/CMakeLists.txt`, then
builds `nextpnr-generic`. Upstream bumps = move the pin + re-copy. If we ever upstream, we cut a
branch from the pin with this dir added. We never hand-maintain a diverged fork.

## The device is DATA, not code

The uarch does **not** hard-code the fabric. `emit_uarch_db.py` (in `engine/`) runs the proven
`arch.py` graph generator against a recording fake-`ctx` and dumps the *entire* device graph to flat
CSV. The uarch's `init()` dumb-loads those CSVs and replays them 1:1 into nextpnr. Zero graph logic
in C++; the graph stays inspectable in AGaMEMnon; guaranteed identical to the Python arch.

Verified 2026-07-08: emit captures the full graph byte-count-for-count —
`lutk=4, wires=50047, bels=2173, belpins=14950, pips=326760` (incl. Qin self-feedback, FF-feedback
bridges, MCU-edge, exit-feeder whitelist, conduction-gated edges).

### Data contract (the `dev_*.csv` the loader consumes)

| file | columns |
|---|---|
| `dev_meta.csv`    | `key,value` — `lutk`, counts, source `arch.py`, `AGAMEMNON_*` env digest |
| `dev_wires.csv`   | `name,type,x,y` — e.g. `X1Y1_IMUX00,IMUX,1,1` |
| `dev_bels.csv`    | `name,type,x,y,z` — e.g. `X1Y1_SLICE0,GENERIC_SLICE,1,1,0` |
| `dev_belpins.csv` | `bel,pin,wire,dir` — `dir ∈ {in,out,inout}`; pins like `I[0]`,`CLK`,`F`,`Q` |
| `dev_pips.csv`    | `name,type,src,dst,delay_ns,x,y,z` — pip name is `{srcwire}.{dstwire}` |

Regenerate with:
```
python engine/emit_uarch_db.py --arch <arch.py> --data <chipdb> --out <dir> [--env K=V ...]
```
Emit from AGaMEMnon's own `engine/arch.py` — it was reconciled to the workbench (current silicon truth)
in the 2026-07-09 engine sync, so the shipped `arch.py` and the workbench arch now match.

## The hooks (what makes this more than generic)

- **`init(Context*)`** — load `dev_*.csv`, replay `addWire/addBel/addBelInput/addBelOutput/addPip`,
  `setLutK`. Data-file path passed via a uarch option (`-o db=<dir>` / `--vopt`).
- **`checkPipAvail(PipId)`** — conduction gate. NOTE: emitted pips are *already* conduction-gated by
  `arch.py` (it loads `master_conduction.csv` + exit-feeder whitelist), so this can start permissive
  and only tighten if we later emit the full ungated graph + a `conducts` column.
- **`isBelLocationValid(BelId, bool)`** — THE point of the port. Encodes, from
  `engine_work/pin_densepack.py` + `pin_ahb_condplace.py`:
  1. even-slot rule (cells on even `z`, skip dead-dest slots) — `xbar_conduction.csv`;
  2. conducting-pair edge check (a cell's placed deps must sit on tiles that conduct to/from it) —
     inter-tile RMUX adjacency from `master_conduction.csv`; Qin self-feedback excluded;
  3. **exit-lane reachability** — the FF driving an `MCU_DOUT` net must sit on a tile that reaches
     `EXIT_TILE=14,12`. This is the assumption with no in-tree precedent; it's why we de-risk first.
- **clustering** — carry / LUT+FF via inherited `BaseArch` `constr_*` (later stage).
- Output: stock `--write out.json`; `bitgen_seq.py` consumes it unchanged (names match § data contract).

## Staged de-risk (each stage = a silicon checkpoint)

1. **Pipeline proof** — load graph + *trivial* `isBelLocationValid` → place a known-good combinational
   design (inverter) → route → JSON → bitgen → silicon. Proves org + build + handoff end-to-end.
2. **Packing legality** — add conduction gate + even-slot/conducting-pair `isBelLocationValid` →
   place a known-good counter *natively, hook-free* → silicon distinct-value.
3. **Exit-reachability** — add the reachability gate → the pivotal test. If dense packs stay
   routable with the exit rule as a hard reject, the whole backend direction is validated.

Honest bound: no backend is proven to pack SERV; stage 3 is where we learn whether the reachability
predicate is cheap enough for the placer hot-loop and actually yields routable dense packs.

## Build

Target: **MSYS2 / mingw-w64** (run in the "MSYS2 MINGW64" shell). One-time deps:
```
pacman -S --needed mingw-w64-x86_64-cmake mingw-w64-x86_64-ninja mingw-w64-x86_64-gcc \
                   mingw-w64-x86_64-boost mingw-w64-x86_64-eigen3 git
```
Then `./build.sh` — clones nextpnr into `AGaMEMnon/third_party/nextpnr`, overlays `agrv2k.cc`,
patches `generic/CMakeLists.txt`, and builds `nextpnr-generic.exe`. Idempotent; re-run after edits.

Generate the chipdb CSVs the uarch loads (`-o chipdb=<dir>`):
```
python ../../emit_uarch_db.py --arch <workbench arch.py> --data <workbench chipdb> --out <dir>
```

## Status

- [x] DB-emit path (`emit_uarch_db.py`) — written + verified on the full graph (326,760 pips captured).
- [x] `agrv2k.cc` skeleton — CSV loader (`init`/`load_db`) + registration; `pack`/`isBelLocationValid`
      are stage-gated stubs (permissive) pending the build + placement bring-up.
- [x] `build.sh` overlay build script (MSYS2/mingw-w64; clone + copy-in + CMake patch).
- [x] **First build** (2026-07-08, WSL Ubuntu-24.04, g++-13) — `--uarch` lists `agrv2k`; graph-load
      smoke test (empty top module) prints `lutk=4 wires=50047 bels=2173 belpins=14950 pips=326760`,
      routes, and `--write`s the routed JSON. Zero C++ fixes; nextpnr @ `2b560ad0` (`main`).
- [x] pin nextpnr commit — `build.sh` `NEXTPNR_PIN=2b560ad0ccc6e7e93ad8bd6cb0f88f925bbb314b`
      (YosysHQ/nextpnr @ 2026-06-19, the commit the uarch was built + silicon-validated against; fetched+
      checked out reproducibly). [ ] still TODO: convert `third_party/nextpnr` to an actual git submodule.
- [x] **Stage 1 (2026-07-09):** `comb.v` end-to-end through the uarch → routed JSON → bitgen → **silicon
      config-accept** (`STAT=0x000f0002`). The uarch→bitgen→hardware handoff is proven.
- [~] **Stage 2 (2026-07-09):** `isBelLocationValid` implemented. The **even-slot invariant** (slices on
      even z; even→even always conducts intra-tile) is always-on and **routes a 513-cell LFSR densely**
      (24% util). The **conducting-pair** inter-tile check (adj from `master_conduction.csv`, loaded into
      the uarch) is correct but as a HARD reject nextpnr's SA can't converge (fails after ~33k attempts on
      the sparse graph) → gated behind `AGRV2K_CONDPAIR=1`. **Conclusion:** inter-tile conduction must move
      to the router (`checkPipAvail` / a `CONDUCTION_GATE`-emitted devdb) + HeAP wirelength clustering, not
      a placement reject. That + silicon-validation of a dense readable design is the remaining Stage-2 work.
- [x] **Stage 2 done (2026-07-09): MULTI-BIT SEQUENTIAL COMPUTES on silicon through the uarch.** Toggle FF,
      2-bit and 4-bit counters read back `distinct` values over AHB. The solve was two parts, both proven:
      (a) **conduction-GATED devdb** (`emit_uarch_db --env AGAMEMNON_CONDUCTION_GATE=1 ...` → 156,972
      conducting pips) so the router can't pick electrically-dead pips — this is what silently froze every
      earlier sequential design; (b) **conduction-aware placer** `pack_condplace` (greedy, `AGRV2K_CONDPLACE`),
      embedding cells on conducting tile-pairs, with `tile_adj` built from the gated devdb's own pips so placer
      == router. Plus `pack_mcu_edge` (bind MCU_DOUT by name), `fanout_split` (net replication for the
      conducting-fanout limit), the sub-4-input-LUT `cells_map` pad, and `AGRV2K_NO_FBBRIDGE`. See
      `examples/uarch_sequential.md`.
- [ ] **Stage 3 (SERV) — blocked on placer scale.** The conduction-aware placer caps ~10–15 cells (greedy
      gets cornered on the sparse conducting graph; an 8-bit counter ≈26 cells fails). SERV (~1800 cells) needs
      a **scalable** conduction-aware placer (analytical/force-directed + conduction refinement, or a
      conduction-aware seed for nextpnr HeAP/SA), then BRAM program-mem + pad-LED. The sequential foundation
      it builds on is done. Hardware carry stays banked (own-Q wall; re-confirmed against the gate).
