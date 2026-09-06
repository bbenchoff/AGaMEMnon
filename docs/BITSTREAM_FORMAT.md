# AGRV2K bitstream format

This document specifies the fabric image formats emitted and consumed by
AGaMEMnon.

Format validity is not functional qualification. A correct length, header,
decompression, CRC, feature map, and FCB-accepted image can still be wrong on
silicon; the campaign recorded 13 such correctness escapes at the composition
level. [STATUS.md](STATUS.md) defines which exact emitted profiles are
qualified.

## Compressed `.bin`

A compressed fabric image is an eight-byte header followed by an LZW stream:

```text
offset  size  field
0       4     DEVICE_ID = 0x40200001, stored 40 20 00 01
4       4     max_index = 0x0000ffff, stored 00 00 ff ff
8       ...   variable-width LZW stream
```

There is no outer file CRC. Integrity is checked on the decompressed raw
configuration.

### LZW parameters

- 8-bit literals use codes 0 through 255.
- CLEAR is 256.
- The first dictionary code is 258.
- There is no end-of-information code.
- Code width starts at 9 bits.
- The dictionary is cleared when the next code reaches 1024.
- Codes are packed most-significant-bit first.
- The final byte is zero-padded.

The stream always decodes to a 99,936-byte raw configuration. The codec is in
`agamemnon/engine/lzw_codec.py`.

## Uncompressed image

The uncompressed SRAM image is the same eight-byte header followed directly
by the 99,936-byte raw configuration, for a total size of 99,944 bytes.

The raw layout is:

| Range | Contents |
|---|---|
| `[0:164]` | global and configuration-chain preamble |
| `[164:99932]` | tile and routing configuration |
| `[99932:99936]` | configuration CRC |

The preamble is emitted by `engine/preamble.py`, not copied from the selected
canvas. Its record descriptors and idle chains are reconstructed constants;
the release clock-distribution profile and seven byte-exact PLL ratios are
explicit generated profiles. Their vendor-oracle hashes and hash modes are
pinned in `agamemnon/chipdb/pll_profile_manifest.json`. `agamemnon explain`
identifies an exact supported profile or reports custom preamble bytes by region.

The CRC is CRC-32/BZIP2 with polynomial `0x04C11DB7`, initial value and final
XOR `0xffffffff`, no input or output reflection. It covers
`header[0:8] + raw[0:99932]` and is stored big-endian in the final raw word.

The fabric configuration block reports `ERR_CRC` for an invalid value. A
successfully active configuration reports `FCB STAT = 0x000f0002` on the
qualified device.

## Physical feature mapping

The canonical `.agasc` feature map names 300,204 distinct physical
configuration bits across 210 tile coordinates (as of the 2026-08-16 shipped
tables; the count moves with table promotions). Families include LUT truth
tables, BRAM initialization, routing muxes, IO, clocks, carry, and control
fields. This count is derived from the shipped tables after aliases that name
the same physical bit are collapsed.

Configuration coordinates `(top_wl, top_bl)` map into the raw image by rank
among the used bit-lines of each word-line:

```text
rank = index of top_bl in the sorted used bit-lines for top_wl
byte = 116 * top_wl + rank // 8 + 164
bit  = 7 - (rank % 8)
```

Reserved bit-line gaps are not stored. LUT truth tables use complemented SRAM
polarity. The mapping implementation is `agamemnon/engine/physmap.py`.

## Routing selectors

A configurable routed edge sets a two-hot selector pair in its destination
RMUX or IMUX block. An RMUX group contains six independent 10-bit blocks; an
IMUX group contains four independent 12-bit blocks.

Release builds accept these selector sources:

- conflict-free physical edge encodings from `sel_edge_pairs.agdb`;
- tile-relative encodings for which every physical observation agrees;
- separately qualified MCU-edge entry/exit and special-block tables.

Conflicting, predicted, legacy, or unresolved general-routing selectors fail
release-strict bitgen. The release graph is filtered to the same accepted encoding
set, so routing and bitgen enforce the boundary independently.

The opt-in `research-unsafe` policy may instead consume the normalized
vendor-derived conflict atlas, corpus-majority/context rows, decoded templates,
and trained predictions. It records the evidence-class counts and research
manifest hash in a mandatory policy sidecar. An unresolved selector still
fails, and any edge carrying negative silicon evidence
(`dead_edges_silicon.csv`) remains unconditionally absent from the graph.
All 14 historical entries were re-qualified as conducting; the independent
`IMUX17@14,8->RMUX69@14,8` exclusion remains in the table.

Special-block corridor tables are also subject to a logical-cell boundary.
A vendor path containing `IMUX -> alta_slice -> OMUX` describes a configured
LUT buffer, not two free routing selectors. Architecture generation therefore
does not expose rows touching `alta_slice` as ordinary PIPs; the design must
place a LUT and bitgen must emit its INIT. This rule is silicon-backed: treating
those rows as transparent route-throughs produced stuck-high HRDATA bits 11,
15, and 19, while the corrected strict rebuild returned the expected value on
all 32 lanes.

The qualified full External-AHB constant endpoint exercises MCU-edge entry and
exit encodings, router2 allocation, router1 legality re-check, and strict
bitgen with zero unmapped PIPs. Its two retained hardware records and artifact
hashes are in
`qualification/mcu_ahb_constant_slave_evidence.jsonl`.

## Baseline canvas

The build base is a from-scratch design-neutral image
synthesized by `agamemnon/engine/default_frame.py` from promoted data tables
(body 100% byte-exact vs the decoded canvas; silicon-qualified in
`qualification/fabric_base_evidence.jsonl`). `agamemnon/chipdb/fabric_default.bin`
remains shipped as a decode reference and differential anchor and is used only
when an explicit `AGAMEMNON_BASELINE` path selects it; its stored trailing CRC
is stale, so it is a template, not a directly loadable image. On either base,
bitgen replaces the complete preamble, clears design-dependent routing and
placed logic fields, applies the routed design and supported hard features,
and regenerates the CRC.

The base is design-neutral and contains no routed user design.

## `.agasc`

`.agasc` is a lossless text representation of the raw configuration. Named
asserted features are grouped by tile; asserted bits without a shipped semantic
name are preserved as sparse `.raw` records.

```text
.agasc 1
.device 0x40200001
.max_index 0x0000ffff
.raw_length 99936
.crc auto
.tile 10 4
+CFG_LUT[0]
+CFG_OMUX0[2]
.end
.raw 000080 ff00
```

The assembler rejects unknown or duplicate features, overlapping raw ranges,
and raw writes to named bits. `.crc auto` regenerates the CRC; `.crc preserve`
is intended for analysis of deliberately invalid images.

```bash
agamemnon to-agasc fabric.bin -o fabric.agasc
agamemnon from-agasc fabric.agasc -o rebuilt.bin
agamemnon from-agasc fabric.agasc --uncompressed -o rebuilt-raw.bin
```

## Commands

```bash
# Routed JSON to uncompressed and compressed images
agamemnon pack routed.json design.bin

# Image to raw configuration
agamemnon unpack design.bin.comp -o raw.img
agamemnon decode design.bin.comp -o raw.img

# Raw configuration to compressed image
agamemnon encode raw.img -o design.bin.comp

# Edit one placed LUT without rerouting
agamemnon edit-lut design.bin --le 20,12,1 --init 0x96e9 -o edited.bin

# Semantic image inspection and comparison
agamemnon explain design.bin
agamemnon diff old.bin new.bin
```

`decode`, `unpack`, and the inspection commands recognize compressed and
uncompressed inputs where applicable.
`explain --json` distinguishes the actual compressed or uncompressed source,
records its byte length and SHA-256, and separately records the canonical
uncompressed content hash. `diff --json` retains that provenance for both
inputs, so semantically identical images in different containers remain
auditable rather than collapsing to an unlabeled decoded hash.

## Flash boot

At power-on, the boot ROM reads the fabric pointer from option bytes. For a
compressed layout it executes the configured decompressor blob, inflates the
99,936-byte raw image, and streams it into the FCB. The supported persistent
workflow replaces the compressed image at an existing option pointer and
preserves the decompressor.

See [PROGRAMMING.md](PROGRAMMING.md) and
[flashboot/FLASH_LAYOUT.md](flashboot/FLASH_LAYOUT.md).
