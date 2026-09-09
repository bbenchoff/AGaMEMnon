# AGaMEMnon capability audit

**Date:** 2026-09-09  
**Tree:** `main`, commit `1a2d8ce5ba87d1099ececcdea6da5ca8513ebbe9`

This audit describes what the public AGaMEMnon tree can do with ordinary
settings, what is bounded to an authenticated profile, and what remains open.
Passing a build or reproducing a retained image is not treated as proof of
arbitrary silicon correctness.

## What works with normal settings

The public flow performs Verilog synthesis, architecture-aware packing,
placement, directed routing, strict validation and bitstream emission for the
supported AG32/AGRV2K device database. It supports ordinary LUT/FF logic,
carry chains in qualified compositions, fixed supported I/O paths, MCU/AHB
endpoints, clocks in the documented profiles, and the ordinary source builds
listed below.

The current default packing flow includes tile compaction, control-group
repartition when a complete group cannot be placed, carry-ingress preflight
with data-LUT fallback, and a classified uncompacted retry. It also measures
qualified native-control sharing candidates from an immutable isolated
baseline. A mixed tile has one native enable group plus ordinary FFs; a dual
tile has two native groups and no ordinary FFs. The profiles are never combined
automatically.

Fresh ordinary builds retained in AG32-Docs route and emit with these measured
results:

| Design | Slices | Occupied tiles | Cells/tile | Image SHA-256 |
|---|---:|---:|---:|---|
| regbank16 | 68 | 6 | 11.33 | `8eeb228087f2d0e1828a1343540c7a5586b3198780dcaa083473ac66355d0b5e` |
| addsub16 | 151 | 12 | 12.58 | `5bfdb3de75affb817e052e619933a8ad5834b45ae029f4e10dbea1d13438eddb` |
| util20 | 434 | 39 | 11.13 | `731e99b03cfae327dfe23034b2deb5c4c43aafefeebd3449631cbc0ad6cd78a2` |

The regbank16 occupancy diagnosis covers all 68 cells and 12,784 single-move
trials. It records 5,325 legal moves and 7,459 rejections: 376 fixed
bindings, 5,870 fixed-endpoint reachability, 14 local-output-pair, 1,168
region and 31 shared-ingress-contention rejections. This is a single-move
legality audit, not a simultaneous full-router proof. The baseline has no
native-enabled registers, so native-control isolation was not the explanation
for its original 16-tile spread.

The current util20 routed netlist has 280 registers, 277 native-enabled
registers and zero named feedback-buffer cells. Its remaining density gap is
therefore not explained by the retired feedback-buffer diagnosis.

## Native control and clocks

Mixed and dual native-control compositions were qualified on silicon using the
MCU bus clock: each candidate passed 3/3, controls passed 2/2, and the
reference passed 1/1. The session used SRAM only, wrote no flash or option
bytes, issued final reset, released custody and left the fence count at 74.
The mixed fixture used 96 slices in 9 tiles versus 10 isolated; the dual
fixture also used 96 slices in 9 tiles. These results qualify those exact
compositions, not arbitrary clock sources, arbitrary native-enable populations,
or mixed-and-dual occupancy in one tile.

Clock resource validation is fail-closed and binds the route, module,
environment and qualified image identity. Partial exact timing overlays exist,
but most wires use conservative fallback values. Clock skew, hard-block and
BRAM timing, package effects, broad PVT behavior and a general Fmax guarantee
are not established.

## BRAM and memory

The synthesis flow contains an inferred `ALTA_BRAM9K` mapping and a strict
configuration emitter. The emitter requires a complete decoded configuration
surface and refuses a tile whose fields would otherwise silently disappear.
Supported ordinary BRAM behavior is deliberately narrow:

* initialized single-port read-only x1/x18 behavior at the documented X13Y4
  composition, with the qualified MCU-bus-clock environment;
* four fixed-address TMUX9 source profiles, each bound to an exact module,
  route and image checkpoint; and
* two authenticated historical read/write profiles that are replayable under
  their closed qualified mode.

The ground-route repair and checkpoint/fingerprint gates fixed reproducibility
for the installed BRAM profiles. They do not establish new memory semantics.

The following are still unsupported or unqualified:

* general inferred writable RAM;
* general true dual-port RAM;
* arbitrary BRAM sites, clocks, widths, modes or output corridors;
* read-during-write collision policies (`old`, `new` or `no_change`) on silicon;
* arbitrary initialization and port-enable/reset combinations; and
* the initialized x1/x18 read-zero escape (`VP-AGM-006`), whose affected images
  remain refused.

The recent packing and routing work can reduce congestion around a BRAM and
make its surrounding address/data logic easier to place. It does not qualify
the BRAM clock, read path, write path or collision behavior. ABC9 and
reset/enable synthesis alternatives likewise require BRAM-specific A/B and
silicon checks before admission.

## Routing, placement and capacity

The compactor scores locality separately from Router2 delay and retains
routing legality. The util20 trace records actual tentative simultaneous wire
ownership and identifies persistent reset/competitor conflicts at
`X16Y4_RMUX24` and `X15Y4_RMUX70`; pairwise wire-disjoint alternatives exist
for those cases. The trace intentionally excludes other nets and configuration
resources, so it is not a proof that arbitrary denser placement will route.

The improvements are substantial but not vendor-level in all cases. The vendor
reference packs roughly 13.6–15.6 cells/tile for the compared designs; the
ordinary results above remain below that density, especially util20. Compact
util20 attempts below the qualified 39-tile result can still time out, and no
physical speedup has been claimed.

The selector graph repair withdraws the invalid RMUX20-to-RMUX27 relative rule
without admitting a replacement edge. This protects correctness and preserved
the retained image gate; it is not a general route-capacity expansion.

## I/O, MCU and register behavior

Several exact pad, MCU/AHB, UART, SPI, I2C, DMA and local-interrupt
compositions are qualified as documented in `STATUS.md` and the associated
qualification records. They are fixed, bounded routes and contracts. Generic
I/O placement, arbitrary MCU readback fanout, arbitrary direct-D sites,
unqualified register-control compositions, alternate bus clocks, broad AHB
window semantics and arbitrary peripheral modes remain outside the supported
claim.

The clock-enable investigation exposed a real observation-path failure in its
first fixture: the MCU canary used shared constant read lanes and did not
discriminate. That image was withdrawn; no enable fence was removed. This is a
known limitation of the evidence path, not evidence that registers are frozen.

## Correctness and safety status

All 74 silicon-negative fences remain active. They cover image and logical
negative entries across the known ALU, FSM, rotate/reset, add/sub reset, BRAM,
wide-clock/state, physical-input and density escapes. In particular, a clean
routed Boolean model does not imply silicon correctness for a new composition.

The project has byte-identity gates for retained images, strict graph and
configuration fingerprints, path-leak and documentation checks, append-only
evidence validation, and CI across Linux, Windows and macOS. The corrected
main CI run `34340670421` passed all eight jobs, including the AGRV2K
end-to-end build and the complete Python/Windows suites. These are software
and reproducibility guarantees; they are not additional silicon qualification.

## Remaining priority work

1. Root-cause and repair VP-AGM-006 through a BRAM-specific differential
   investigation of read data, initialization, clock/enable fields and local
   routing, followed by a discriminating silicon contract.
2. Expand BRAM support one composition at a time: writable single-port,
   dual-port, collision policy, alternate sites and clocks, with complete
   field decode and fresh ordinary-source qualification for each.
3. Improve simultaneous routing-aware compaction beyond the current qualified
   39-tile util20 result, measuring resource conflicts across all nets rather
   than pairwise reachability alone.
4. Extend clock/control compositions and timing models only where directed
   witnesses, exact encoding checks and silicon contracts support them.
5. Continue the remaining 74 correctness escapes and establish broad timing,
   capacity and arbitrary-Verilog evidence before making vendor-parity claims.

This audit is the current capability boundary. It intentionally records useful
implemented behavior without turning bounded evidence into a universal claim.
