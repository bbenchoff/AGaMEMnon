# BRAM DataOut exits: the parity lanes and every Port-B lane (2026-09-25)

## The gap

The BRAM tile presents each port's 18 output lanes on `BufMUX` wires. Lanes 0-7 and 9-16 use
`BufMUX00..15` (Port A) and `BufMUX16..31` (Port B); the parity lanes do not: `DataOutA[8]` is
`X13Y4_BufMUX32`, `DataOutA[17]` is `BufMUX33`, `DataOutB[8]` is `BufMUX34`, `DataOutB[17]` is
`BufMUX35`. Until this change no device graph admitted a single pip out of those four wires:

- the tile model (`chipdb/bram9k_edges.csv`) listed a few candidate exits, but bitgen requires a
  byte-exact `chipdb/bram_pip_cfg.csv` row for any `BufMUX -> RMUX` hop and none existed for a
  parity wire, so the loader pruned them ("no exact config");
- the two candidates that did have config rows (`BufMUX32 -> RMUX08`, `BufMUX33 -> RMUX44`) were
  kept out by the witnessed-feeder rule, which admits only board-witnessed feeders into a
  ring-witnessed BRAM-tile terminal and read that evidence from `ring_witness_conduction.csv`
  alone.

The symptom was that every full-width read failed packing:

    agrv2k: BRAM output DataOutA[17] reaches slice input pins in only 0 tile(s) and none of them is free for an identity bridge

## The evidence

The vendor tool routes those exits routinely. Thirty-nine BRAM mode designs were manufactured by
instantiating the vendor primitive directly (one design per width/port/clock/output-register
mode, each proved in simulation against the vendor model, nominal and fault-injected), built
through the vendor back end, and measured on the board behind a positive control: 42 of 46 images
passed their self-checking heartbeat oracle, and the four failures were inferred corpus designs
whose vendor synthesis collapsed the RTL, not primitive modes.

Decoding the passing images' routes gave 29 distinct parity-lane first hops across the BRAM
sites, ten of them at `X13Y4`, and 28 further `X13Y4` first hops off the ordinary Port-B lanes
(`BufMUX16..31`) that had no byte-exact row either: with the parity lanes alone admitted, the
dual-port 18/18 design still failed packing on `DataOutB[10]`. Each destination's selector block in the image holds one 2-hot
pair, identical in every image that uses the hop (`BufMUX32 -> RMUX01` appears in four passing
images with the same pair). The pair's cells map through `chipdb/bram_cell.csv` to the absolute
bytes bitgen writes.

## The change

- `chipdb/bram_vendor_recovered_exits.csv`: the 57 observed hops (29 parity-lane, 28 Port-B) with
  their 2-hot selector pair and the number of passing images. Loaded as per-position conduction
  evidence; the witnessed-feeder rule lets each row join the whitelist of a terminal that
  `ring_witness_conduction.csv` already restricts, but a recovered exit never restricts a terminal
  by itself (that table lags the campaign ledger by one promotion, and 21 of the 22 mesh feeders a
  first cut pruned that way were ledger-witnessed). The loader admits a recovered exit only at
  `X13Y4`, the site its bytes are mapped for, so the tile model's `X13Y1/Y2` rows for the same
  wires stay out.
- `chipdb/bram9k_edges.csv`: topology rows for the 28 `X13Y4` hops the tile model lacked.
- `chipdb/bram_pip_cfg.csv`: the 76 byte-exact cells (two per hop) for the 38 `X13Y4` hops,
  in the destinations' own selector blocks (checked by `tests/test_bram_pip_cfg_consistency.py`).
- Every graph gains exactly those 38 pips (strict 319,640 -> 319,678; tiered 332,366 -> 332,404;
  the shared-control graphs likewise); the previous identities are retained as
  `PRE_BRAM_PARITY_EXITS_20260925_PHYSICAL_GRAPHS`.
- `synth/prims.v`: the open `ALTA_BRAM9K` now declares `PACKEDMODE`, `DLYTIME` and `RSEN_DLY`, so
  an instantiation that sets one reaches bitgen's experimental-field gate (which still refuses a
  non-zero value without `AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG`) instead of failing in synthesis.

The other sites' observations (`X13Y2`, `X13Y3`) are recorded as evidence only: bitgen applies
`bram_pip_cfg.csv` bytes at `X13Y4` alone, and the measured byte offsets differ by a constant
7,888 bytes per tile row, so mapping them is a follow-up, not a guess.

## Admitted versus witnessed, per port and lane (release-strict, after this change)

Every DataOut lane of both ports now has at least one admitted exit at `X13Y4`, and every admitted
exit carries a witness: `L` = a ring/corpus witness in the campaign ledger, `Vn` = observed in `n`
vendor images that passed on the board. The right-hand column lists vendor-passing first hops that
are still not admitted: the Port-A ones leave the tile into `X14Y4` LogicTile muxes, whose
codewords live in the LogicTile selector tables rather than `bram_pip_cfg.csv` (the
`vendor_recovered_edges.csv` mechanism, a follow-up); the six Port-B ones (`BufMUX19 -> RMUX03`,
`BufMUX25 -> RMUX61`, `BufMUX26 -> RMUX68`, `BufMUX27 -> RMUX51`, `BufMUX28 -> RMUX74`,
`BufMUX29 -> RMUX87`) already have byte-exact rows and are kept out only by ring-restricted
terminals; adding them to the evidence table admits them (data only).

| port | lane | wire | admitted exits in release-strict (witness: L=ledger ring/corpus, V=vendor PASS images, -=none) | vendor PASS first hops not admitted |
|---|---|---|---|---|
| DataOutA | 0 | BufMUX00 | X14Y4_RMUX09(L/V2) | X14Y4_RMUX05(V1), X14Y4_RMUX11(V2), X14Y4_RMUX16(V1), X14Y4_RMUX20(V2) |
| DataOutA | 1 | BufMUX01 | X14Y4_RMUX20(L) | X14Y4_RMUX03(V3), X14Y4_RMUX05(V1), X14Y4_RMUX09(V2), X14Y4_RMUX11(V1), X14Y4_RMUX22(V1) |
| DataOutA | 2 | BufMUX02 | X14Y4_RMUX02(L/V1) | X14Y4_RMUX08(V1), X14Y4_RMUX10(V2), X14Y4_RMUX13(V1), X14Y4_RMUX17(V1), X14Y4_RMUX19(V1), X14Y4_RMUX23(V1) |
| DataOutA | 3 | BufMUX03 | X14Y4_RMUX08(L), X14Y4_RMUX19(L/V2) | X14Y4_RMUX04(V2), X14Y4_RMUX13(V1), X14Y4_RMUX15(V3), X14Y4_RMUX17(V1) |
| DataOutA | 4 | BufMUX04 | X14Y4_RMUX25(L/V2), X14Y4_RMUX38(L/V1) | X14Y4_RMUX27(V1), X14Y4_RMUX29(V1), X14Y4_RMUX35(V2), X14Y4_RMUX40(V1), X14Y4_RMUX44(V1) |
| DataOutA | 5 | BufMUX05 | X14Y4_RMUX25(L/V1), X14Y4_RMUX38(L) | X14Y4_RMUX31(V1), X14Y4_RMUX33(V2), X14Y4_RMUX35(V3), X14Y4_RMUX40(V2) |
| DataOutA | 6 | BufMUX06 | X14Y4_RMUX39(L/V3) | X14Y4_RMUX28(V1), X14Y4_RMUX41(V2), X14Y4_RMUX43(V2), X14Y4_RMUX47(V1) |
| DataOutA | 7 | BufMUX07 | X14Y4_RMUX32(L/V1), X14Y4_RMUX45(L/V2) | X14Y4_RMUX26(V1), X14Y4_RMUX37(V1), X14Y4_RMUX41(V1), X14Y4_RMUX47(V2) |
| DataOutA | 8 | BufMUX32 | X13Y4_RMUX01(V4), X13Y4_RMUX03(V1), X13Y4_RMUX13(V1) |  |
| DataOutA | 9 | BufMUX08 | X14Y4_RMUX62(L) | X14Y4_RMUX51(V2), X14Y4_RMUX53(V2), X14Y4_RMUX59(V2), X14Y4_RMUX64(V1) |
| DataOutA | 10 | BufMUX09 | X14Y4_RMUX55(L) | X14Y4_RMUX49(V3), X14Y4_RMUX53(V1), X14Y4_RMUX57(V1), X14Y4_RMUX70(V2) |
| DataOutA | 11 | BufMUX10 | X14Y4_RMUX69(L) | X14Y4_RMUX50(V1), X14Y4_RMUX52(V1), X14Y4_RMUX63(V2), X14Y4_RMUX65(V1), X14Y4_RMUX67(V1), X14Y4_RMUX71(V1) |
| DataOutA | 12 | BufMUX11 | X14Y4_RMUX71(L/V1) | X14Y4_RMUX56(V2), X14Y4_RMUX58(V2), X14Y4_RMUX61(V1), X14Y4_RMUX65(V1) |
| DataOutA | 13 | BufMUX12 | X14Y4_RMUX75(L), X14Y4_RMUX92(L) | X14Y4_RMUX73(V1), X14Y4_RMUX79(V2), X14Y4_RMUX83(V1), X14Y4_RMUX88(V1), X14Y4_RMUX94(V2) |
| DataOutA | 14 | BufMUX13 | X14Y4_RMUX92(L) | X14Y4_RMUX75(V1), X14Y4_RMUX77(V3), X14Y4_RMUX83(V1), X14Y4_RMUX86(V2) |
| DataOutA | 15 | BufMUX14 | X14Y4_RMUX80(L/V1) | X14Y4_RMUX76(V1), X14Y4_RMUX82(V1), X14Y4_RMUX89(V2), X14Y4_RMUX93(V2) |
| DataOutA | 16 | BufMUX15 | X14Y4_RMUX74(L) | X14Y4_RMUX76(V1), X14Y4_RMUX87(V3), X14Y4_RMUX91(V3) |
| DataOutA | 17 | BufMUX33 | X13Y4_RMUX25(V1), X13Y4_RMUX27(V1), X13Y4_RMUX31(V2), X13Y4_RMUX38(V1), X13Y4_RMUX43(V1) |  |
| DataOutB | 0 | BufMUX16 | X13Y4_RMUX08(L/V1), X13Y4_RMUX15(V2) |  |
| DataOutB | 1 | BufMUX17 | X13Y4_RMUX08(L), X13Y4_RMUX13(V2), X13Y4_RMUX15(L/V1) |  |
| DataOutB | 2 | BufMUX18 | X13Y4_RMUX01(V1), X13Y4_RMUX03(L), X13Y4_RMUX18(V1), X13Y4_RMUX20(L/V1) |  |
| DataOutB | 3 | BufMUX19 | X13Y4_RMUX12(V1), X13Y4_RMUX20(L/V3) | X13Y4_RMUX03(V2) |
| DataOutB | 4 | BufMUX20 | X13Y4_RMUX39(V2), X13Y4_RMUX45(L/V4) |  |
| DataOutB | 5 | BufMUX21 | X13Y4_RMUX26(L/V1), X13Y4_RMUX30(V1), X13Y4_RMUX39(V2), X13Y4_RMUX45(V2) |  |
| DataOutB | 6 | BufMUX22 | X13Y4_RMUX31(V4), X13Y4_RMUX33(V2), X13Y4_RMUX38(L) |  |
| DataOutB | 7 | BufMUX23 | X13Y4_RMUX31(L/V1), X13Y4_RMUX36(V1), X13Y4_RMUX38(V1) |  |
| DataOutB | 8 | BufMUX34 | X13Y4_RMUX49(V1) |  |
| DataOutB | 9 | BufMUX24 | X13Y4_RMUX61(V2), X13Y4_RMUX63(V2) |  |
| DataOutB | 10 | BufMUX25 | X13Y4_RMUX48(V1), X13Y4_RMUX63(V1) | X13Y4_RMUX61(V2) |
| DataOutB | 11 | BufMUX26 | X13Y4_RMUX51(V2), X13Y4_RMUX60(V1) | X13Y4_RMUX68(V1) |
| DataOutB | 12 | BufMUX27 | X13Y4_RMUX66(V1), X13Y4_RMUX68(V2) | X13Y4_RMUX51(V1) |
| DataOutB | 13 | BufMUX28 | X13Y4_RMUX91(V1) | X13Y4_RMUX74(V3) |
| DataOutB | 14 | BufMUX29 | X13Y4_RMUX72(V1), X13Y4_RMUX91(V2) | X13Y4_RMUX87(V1) |
| DataOutB | 15 | BufMUX30 | X13Y4_RMUX79(V3), X13Y4_RMUX86(V1) |  |
| DataOutB | 16 | BufMUX31 | X13Y4_RMUX81(V3), X13Y4_RMUX90(V1) |  |
| DataOutB | 17 | BufMUX35 | X13Y4_RMUX93(V1) |  |

## Silicon results on the open side (2026-09-25, 00:00-01:15) and what they say

Open images of the same modes, built with the default command, behind passing controls:

| mode | port read | lanes checked | open verdict | vendor verdict |
|---|---|---|---|---|
| x1 single-port (`bmd_sp1_c10_o0`) | A | 0 | PASS | PASS |
| x2 single-port (`bmd_sp2_c10_o0`) | A | 1, 2 | RATE_FAIL (0 edges) | PASS |
| x4 true dual-port (`bmd_tdp4_c10`) | A and B | 3..6 | PASS | PASS |
| x9 single-port (`bmd_sp9_c10_o0`) | A | 7, 9..16 | RATE_FAIL (0 edges) | PASS |
| x18 single-port (`bmd_sp18_c10_o0`) | A | 0..17 | RATE_FAIL (0 edges) | PASS |
| x1 simple dual-port (`bmd_sdp1_1_c00`) | B | 0 | RATE_FAIL (0 edges) | PASS |
| x2 simple dual-port (`bmd_sdp2_2_c00`) | B | 1, 2 | RATE_FAIL (0 edges) | PASS |
| x4 simple dual-port (`bmd_sdp4_4_c00`) | B | 3..6 | PASS | PASS |
| x9 write / x4 read (`bmd_sdp9_4_c00`) | B | 3..6 | twice the heartbeat | PASS |

What the routed netlists and the images show (scripts in the workbench scratch
`lane_routes.py`, `compare_exit_sels.py`):

- Every DataOut lane of every failing image leaves the tile on an exit whose selector codeword is
  byte-identical to the one the vendor programmed for the same pip wherever the vendor used it
  (x1 Port B: `BufMUX16 -> RMUX08`, the very exit of the vendor's passing x1 image), and every pip
  on every DataOut route, passing or failing, is ledger- or vendor-witnessed. The exits used only
  by us (`BufMUX01 -> X14Y4_RMUX20`, `BufMUX22 -> RMUX38`, ...) appear in passing images too.
- The input side is the same: address, data-in and control routes carry no unwitnessed pip other
  than same-tile OMUXPRES presentation pips, which passing images use as well.

So the DataOut egress is not what separates PASS from FAIL, and neither is any single routed pip.
What separates them is the lane window: lanes 3..6 deliver on both ports, lane 0 delivers on Port A
but not Port B, lanes 1..2 and 7..16 do not deliver, and the x9-write/x4-read image reads its
pattern twice per sweep (an address alias, not a dead lane). That points at the open flow's handling
of the narrow-mode address low bits and lane windows (the BRAM-pin packing of `AddressA[3:0]` and
the DataIn replication), not at routing. The discriminating vehicle is a read-only memory: an
`INIT_VAL` ROM instantiated directly at x2 (lanes 1..2), x9 (7, 9..16) and x18 (all lanes), with no
write path, boarded on both ports. A ROM PASS moves the fault to the write side; a ROM FAIL keeps it
on the read side, where the per-lane exits and the parity lanes can then be bisected one lane at a
time.

With the exits admitted, the open single-port x18 design (`bmd_sp18_c10_o0`) packs, routes and
emits (all 18 lanes leave the tile; lanes 8 and 17 through `BufMUX32 -> RMUX01` and
`BufMUX33 -> RMUX25`). The dual-port 18/18 design (`bmd_sdp18_18_c00`) now gets past packing too;
it fails later in placement ("Unable to find legal placement for cell `$PACKER_GND`" after 10,001
attempts in every escalation step): a placer capacity problem around the BRAM approach column, a
separate defect from the egress gap this note closes.
