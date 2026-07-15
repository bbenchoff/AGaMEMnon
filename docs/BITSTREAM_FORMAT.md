# AGRV2K bitstream format

This document specifies the fabric image formats emitted and consumed by
AGaMEMnon.

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

The CRC is CRC-32/BZIP2 with polynomial `0x04C11DB7`, initial value and final
XOR `0xffffffff`, no input or output reflection. It covers
`header[0:8] + raw[0:99932]` and is stored big-endian in the final raw word.

The fabric configuration block reports `ERR_CRC` for an invalid value. A
successfully active configuration reports `FCB STAT = 0x000f0002` on the
qualified device.

## Physical feature mapping

The chip database maps 554,800 configuration cells across 213 tiles to named
features. Families include LUT truth tables, BRAM initialization, routing
muxes, IO, clocks, carry, and control fields.

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

- conflict-free physical edge encodings from `sel_edge_pairs.pkl`;
- tile-relative encodings for which every physical observation agrees;
- separately qualified MCU-edge entry/exit and special-block tables.

Conflicting, predicted, legacy, or unresolved general-routing selectors fail
strict bitgen. The release graph is filtered to the same accepted encoding
set, so routing and bitgen enforce the boundary independently.

## Baseline canvas

`agamemnon/chipdb/fabric_default.bin` supplies design-invariant global, IO,
clock, and structural state. Bitgen clears design-dependent routing and placed
logic fields before applying the routed design. It then emits supported clock,
IO, carry, MCU-edge, and BRAM configuration and regenerates the CRC.

The canvas is design-neutral and contains no routed user design.

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
```

`decode`, `unpack`, and the inspection commands recognize compressed and
uncompressed inputs where applicable.

## Flash boot

At power-on, the boot ROM reads the fabric pointer from option bytes. For a
compressed layout it executes the configured decompressor blob, inflates the
99,936-byte raw image, and streams it into the FCB. The supported persistent
workflow replaces the compressed image at an existing option pointer and
preserves the decompressor.

See [PROGRAMMING.md](PROGRAMMING.md) and
[flashboot/FLASH_LAYOUT.md](flashboot/FLASH_LAYOUT.md).
