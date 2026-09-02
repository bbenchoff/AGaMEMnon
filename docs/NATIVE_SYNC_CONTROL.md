# Bounded native synchronous clear

## Verdict

AGaMEMnon has a desk-qualified, default-off candidate for one active-high
synchronous clear-to-zero register at `X14Y12_SLICE0`. It is sufficient to
produce a hashable SRAM-only silicon candidate. It is not yet a silicon
witness, an all-site geometry rule, or a release feature.

The experiment is selected only by
`AGAMEMNON_NATIVE_SYNC_CLEAR_X14Y12_S0=1`. With the option absent or empty,
synchronous reset keeps the established LUT-on-D lowering and the generated
architecture and image behavior remain unchanged.

## Evidence boundary

Four same-site, single-variable compilation pairs independently agreed on the
native mode changes:

- set slice-local `CFG_BYPASSEN[0]`;
- set LogicTile `CFG_TILESYNCMUX[5]`.

The control-signal route varied between seeds, as ordinary routing can. Two
repetitions used the same fully decoded ingress selected for this bounded
candidate:

```text
X15Y12_RMUX90 -> X14Y12_CtrlMUX03 -> X14Y12_TileSyncMUX00
```

Its complete selector write is deliberately explicit and site-local:

- clear `CFG_TILESYNCMUX[0..5]`, then set `[1]` and `[5]`;
- clear `CFG_CTRLMUX[24..47]`, then set `[42]` and `[47]`;
- clear and set `CFG_BYPASSEN[0]` through the existing slice map.

The mode bits are four-pair stable; the selected ingress is twice repeated.
That distinction is retained in code and is why this surface is exact-site and
experimental instead of generalized.

## Public semantic seed

The shared-control model follows the public Cyclone LAB organization only as a
semantic Rosetta Stone: LAB-wide synchronous clear/load controls require a
shared legality boundary and a dedicated control mux, rather than being treated
as ordinary LUT data. The AGRV2K coordinates and configuration cells above come
from AGaMEMnon's own differential and graph evidence, not from those documents.

- [Cyclone III Device Handbook](https://cdrdv2-public.intel.com/654357/cyclone3_handbook.pdf)
- [Cyclone IV Device Handbook](https://cdrdv2-public.intel.com/653974/cyclone4-handbook.pdf)

## Fail-closed implementation

The frontend preserves only Yosys `$_SDFF_PP0_`: positive-edge clock,
active-high synchronous clear, and clear value zero. Every other synchronous
reset, polarity, value, enable combination, asynchronous form, or forged raw
cell follows its existing lowering or is rejected.

The native packer admits exactly one such register, hard-binds it to
`X14Y12_SLICE0`, exposes an `SCLR` BEL pin only there, and accepts only the two
typed control pips above. The strict emitter revalidates the placed cell, scalar
control net, canonical routed path, complete selector codeword, and absence of
carry composition before claiming any image bit.

`qualification/native_sync_clear_x14y12_s0.v` is the control/candidate vehicle.
The default build lowers its reset into LUT data; the opt-in build preserves the
native control. Both return the register state and an independent HADDR[2] echo
to the MCU, so a later board harness can reject a bad stimulus rather than
trusting the candidate output alone.

## Desk emission witness

The bounded vehicle completed release-strict placement, routing, and strict
bitstream emission with zero unmapped selectors. The candidate image SHA-256
is `cd2fb9e50a4f9e8d0fe9b8fb29edd87f0561edd3c761a80d5580599f8cc169d8`.
Its routed netlist contains one `SYNC_CLEAR_POS_ZERO` cell at the exact BEL and
the exact ingress above; decoding the emitted SRAM gives only `[1,5]` in the
six-bit TileSyncMux field and `[42,47]` in the 24-bit CtrlMux field.

The option-off control was also rebuilt from an untouched `origin/main`
checkout with a separately compiled copy of pinned nextpnr. Both the raw image
and compressed image were byte-identical to the option-off build from this
branch. The machine-readable hashes and decoded field values are recorded in
`qualification/native_sync_clear_x14y12_s0_evidence.json`.

## Promotion fence

The option requires `experimental-strict` policy and its explicit option name.
It must remain on a work branch until the preregistered control-first SRAM-only
silicon A/B succeeds under a fresh one-shot human authorization. A successful
one-site witness still does not justify all-site geometry or any other shared
control mode.
