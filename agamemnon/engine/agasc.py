#!/usr/bin/env python3
"""Lossless, per-tile ASCII representation for AGRV2K configuration images.

``.agasc`` is the AGaMEMnon counterpart to IceStorm's ``.asc`` format.  Every
physical bit covered by the shipped feature tables is written once as a named
feature in a ``.tile X Y`` block.  Set bits outside those tables (global
preamble fields and the still-undecoded tail) are retained in sparse ``.raw``
records, so conversion does not discard evidence merely because its semantic
name is not known yet.

Format version 1 is intentionally small and line-oriented::

    .agasc 1
    .device 0x40200001
    .max_index 0x0000ffff
    .raw_length 99936
    .crc auto
    .tile 10 4
    +CFG_LUT[0]
    .end
    .raw 000080 ff00

Only asserted features are listed.  Removing a ``+FEATURE`` line clears it;
adding one sets it.  ``.crc auto`` excludes the stored checksum from ``.raw``
and regenerates CRC-32/BZIP2 when parsing.  ``.crc preserve`` is available for
forensics on deliberately invalid images.
"""

import collections
import csv
import functools
import os
import re
import struct


RAW_LEN = 99936
CRC_OFFSET = RAW_LEN - 4
DEFAULT_DEVICE = 0x40200001
DEFAULT_MAX_INDEX = 0x0000FFFF
_FEATURE_RE = re.compile(r"[A-Za-z0-9_\[\]]+")

# Earlier sources provide more descriptive names for the same physical cell.
# pips_full is the complete routing fallback and therefore deliberately last.
_SOURCES = (
    ("slice_cfg.csv", "feature", None),
    ("bram_cell.csv", "mux", "sel"),
    ("pips_io.csv", "mux", "sel"),
    ("pips_mcuedge.csv", "mux", "sel_index"),
    ("pips_full.csv", "mux", "sel"),
)


class AgascError(ValueError):
    """Malformed or internally contradictory AGaMEMnon ASCII configuration."""


def crc32_bzip2(data):
    value = 0xFFFFFFFF
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = (((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                     if value & 0x80000000 else (value << 1) & 0xFFFFFFFF)
    return value ^ 0xFFFFFFFF


def _feature_name(row, name_column, index_column):
    name = row[name_column]
    if index_column is not None:
        name += "[%s]" % row[index_column]
    if not _FEATURE_RE.fullmatch(name):
        raise AgascError("feature table contains an unsafe name: %r" % name)
    return name


@functools.lru_cache(maxsize=4)
def load_feature_map(data_dir):
    """Return canonical physical-bit and per-tile feature maps.

    ``by_bit[(byte, mask)] = (x, y, feature)`` and the reverse ``by_feature``
    are both one-to-one.  A conflicting shipped table is a hard error rather
    than a silently ambiguous ASCII file.
    """
    data_dir = os.path.abspath(data_dir)
    candidates = collections.defaultdict(list)
    feature_bits = collections.defaultdict(set)
    for priority, (filename, name_column, index_column) in enumerate(_SOURCES):
        path = os.path.join(data_dir, filename)
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                name = _feature_name(row, name_column, index_column)
                key = (int(row["x"]), int(row["y"]), name)
                bit = (int(row["byte"]), int(row["mask"]))
                if bit[0] < 0 or bit[0] >= RAW_LEN or bit[1] not in (1, 2, 4, 8, 16, 32, 64, 128):
                    raise AgascError("invalid physical cell in %s: %r" % (filename, bit))
                candidates[bit].append((priority, key))
                feature_bits[key].add(bit)

    ambiguous = [key for key, bits in feature_bits.items() if len(bits) != 1]
    if ambiguous:
        raise AgascError("feature name maps to multiple physical bits: %r" % (ambiguous[0],))

    by_bit = {}
    by_feature = {}
    for bit, aliases in candidates.items():
        _, key = min(aliases, key=lambda item: (item[0], item[1]))
        previous = by_feature.get(key)
        if previous is not None and previous != bit:
            raise AgascError("canonical feature collision: %r" % (key,))
        by_bit[bit] = key
        by_feature[key] = bit
    return by_bit, by_feature


def _mapped_masks(by_bit):
    masks = bytearray(RAW_LEN)
    for byte, mask in by_bit:
        masks[byte] |= mask
    return masks


def dumps(raw, data_dir, header=None, crc_mode="auto"):
    """Convert a 99,936-byte raw image to deterministic ``.agasc`` text."""
    raw = bytes(raw)
    if len(raw) != RAW_LEN:
        raise AgascError("raw image is %d bytes; expected %d" % (len(raw), RAW_LEN))
    if header is None:
        header = struct.pack(">II", DEFAULT_DEVICE, DEFAULT_MAX_INDEX)
    if len(header) != 8:
        raise AgascError("fabric header is %d bytes; expected 8" % len(header))
    if crc_mode not in ("auto", "preserve"):
        raise AgascError("unknown CRC mode %r" % crc_mode)

    by_bit, _ = load_feature_map(data_dir)
    asserted = collections.defaultdict(list)
    for (byte, mask), (x, y, feature) in by_bit.items():
        if raw[byte] & mask:
            asserted[(x, y)].append(feature)

    device, max_index = struct.unpack(">II", header)
    lines = [
        "# AGaMEMnon ASCII configuration",
        ".agasc 1",
        ".device 0x%08x" % device,
        ".max_index 0x%08x" % max_index,
        ".raw_length %d" % RAW_LEN,
        ".crc %s" % crc_mode,
    ]
    for (x, y), features in sorted(asserted.items()):
        lines.append(".tile %d %d" % (x, y))
        lines.extend("+" + feature for feature in sorted(features))
        lines.append(".end")

    mapped_masks = _mapped_masks(by_bit)
    residual = bytearray(value & (~mapped_masks[i] & 0xFF) for i, value in enumerate(raw))
    if crc_mode == "auto":
        residual[CRC_OFFSET:] = b"\0\0\0\0"
    for offset in range(0, RAW_LEN, 32):
        chunk = bytes(residual[offset:offset + 32])
        if any(chunk):
            lines.append(".raw %06x %s" % (offset, chunk.hex()))
    lines.append("")
    return "\n".join(lines)


def loads(text, data_dir):
    """Parse ``.agasc`` text and return ``(header, raw)``.

    Unknown features, duplicate directives, overlapping raw ranges, and raw
    records that try to set a named bit are rejected.  This keeps hand edits
    fail-closed instead of silently producing an ambiguous image.
    """
    by_bit, by_feature = load_feature_map(data_dir)
    mapped_masks = _mapped_masks(by_bit)
    raw = bytearray(RAW_LEN)
    raw_written = bytearray(RAW_LEN)
    seen_features = set()
    current_tile = None
    version = device = max_index = raw_length = crc_mode = None

    def once(old, name, value, lineno):
        if old is not None:
            raise AgascError("line %d: duplicate %s directive" % (lineno, name))
        return value

    for lineno, original in enumerate(str(text).splitlines(), 1):
        line = original.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        command = fields[0]
        try:
            if command == ".agasc" and len(fields) == 2:
                version = once(version, ".agasc", int(fields[1], 0), lineno)
            elif command == ".device" and len(fields) == 2:
                device = once(device, ".device", int(fields[1], 0), lineno)
            elif command == ".max_index" and len(fields) == 2:
                max_index = once(max_index, ".max_index", int(fields[1], 0), lineno)
            elif command == ".raw_length" and len(fields) == 2:
                raw_length = once(raw_length, ".raw_length", int(fields[1], 0), lineno)
            elif command == ".crc" and len(fields) == 2:
                crc_mode = once(crc_mode, ".crc", fields[1], lineno)
            elif command == ".tile" and len(fields) == 3:
                if current_tile is not None:
                    raise AgascError("line %d: nested .tile block" % lineno)
                current_tile = (int(fields[1], 0), int(fields[2], 0))
            elif command == ".end" and len(fields) == 1:
                if current_tile is None:
                    raise AgascError("line %d: .end outside a tile" % lineno)
                current_tile = None
            elif command == ".raw" and len(fields) == 3:
                if current_tile is not None:
                    raise AgascError("line %d: .raw inside a tile" % lineno)
                offset = int(fields[1], 16)
                payload = bytes.fromhex(fields[2])
                if not payload:
                    raise AgascError("line %d: empty .raw record" % lineno)
                if offset < 0 or offset + len(payload) > RAW_LEN:
                    raise AgascError("line %d: .raw record outside image" % lineno)
                for index, value in enumerate(payload, offset):
                    if raw_written[index]:
                        raise AgascError("line %d: overlapping .raw record at byte %d" % (lineno, index))
                    if value & mapped_masks[index]:
                        raise AgascError("line %d: .raw sets a named bit at byte %d" % (lineno, index))
                    # Residual and named bits are disjoint by construction.
                    # Merge rather than assign so .raw records are order-
                    # independent and cannot clear earlier tile features.
                    raw[index] |= value
                    raw_written[index] = 1
            elif command.startswith("+") and len(fields) == 1:
                if current_tile is None:
                    raise AgascError("line %d: feature outside a tile" % lineno)
                feature = command[1:]
                key = current_tile + (feature,)
                if key not in by_feature:
                    raise AgascError("line %d: unknown feature X%dY%d %s" %
                                     (lineno, current_tile[0], current_tile[1], feature))
                if key in seen_features:
                    raise AgascError("line %d: duplicate feature %s" % (lineno, feature))
                seen_features.add(key)
                byte, mask = by_feature[key]
                raw[byte] |= mask
            else:
                raise AgascError("line %d: unrecognized syntax: %s" % (lineno, original.strip()))
        except ValueError as exc:
            if isinstance(exc, AgascError):
                raise
            raise AgascError("line %d: %s" % (lineno, exc)) from exc

    if current_tile is not None:
        raise AgascError("unterminated .tile block")
    required = {".agasc": version, ".device": device, ".max_index": max_index,
                ".raw_length": raw_length, ".crc": crc_mode}
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise AgascError("missing required directive(s): %s" % ", ".join(missing))
    if version != 1:
        raise AgascError("unsupported .agasc version %r" % version)
    if raw_length != RAW_LEN:
        raise AgascError("unsupported raw length %r; expected %d" % (raw_length, RAW_LEN))
    if not (0 <= device <= 0xFFFFFFFF and 0 <= max_index <= 0xFFFFFFFF):
        raise AgascError("device header fields must be unsigned 32-bit values")
    if crc_mode not in ("auto", "preserve"):
        raise AgascError("unknown CRC mode %r" % crc_mode)

    header = struct.pack(">II", device, max_index)
    if crc_mode == "auto":
        raw[CRC_OFFSET:] = struct.pack(">I", crc32_bzip2(header + bytes(raw[:CRC_OFFSET])))
    return header, bytes(raw)
