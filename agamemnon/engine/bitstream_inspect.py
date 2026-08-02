"""Semantic inspection and comparison of AGRV2K raw configuration images."""
from __future__ import annotations

import hashlib
import struct

from . import agasc, preamble


SCHEMA_VERSION = 1


def _bit_count(value):
    try:
        return value.bit_count()
    except AttributeError:  # Python 3.8/3.9
        return bin(value).count("1")


def describe(header, raw, data_dir, *, include_raw=False, tile=None):
    """Return a stable, JSON-serializable semantic description."""
    if len(header) != 8 or len(raw) != agasc.RAW_LEN:
        raise agasc.AgascError("inspection requires an 8-byte header and 99936-byte raw image")
    by_bit, _ = agasc.load_feature_map(data_dir)
    mapped_masks = agasc._mapped_masks(by_bit)
    grouped = {}
    for (byte, mask), (x, y, feature) in by_bit.items():
        if raw[byte] & mask and (tile is None or tile == (x, y)):
            grouped.setdefault((x, y), []).append(feature)
    tiles = [
        {"x": x, "y": y, "features": sorted(features)}
        for (x, y), features in sorted(grouped.items())
    ]
    residual = []
    unknown_count = 0
    for offset, value in enumerate(raw[:agasc.CRC_OFFSET]):
        unknown = value & (~mapped_masks[offset] & 0xFF)
        unknown_count += _bit_count(unknown)
        if include_raw and unknown:
            residual.append({"offset": offset, "value": unknown})
    stored_crc = struct.unpack(">I", raw[agasc.CRC_OFFSET:])[0]
    expected_crc = agasc.crc32_bzip2(header + raw[:agasc.CRC_OFFSET])
    device, max_index = struct.unpack(">II", header)
    return {
        "schema": SCHEMA_VERSION,
        "device": "0x%08x" % device,
        "max_index": "0x%08x" % max_index,
        "sha256": hashlib.sha256(header + raw).hexdigest(),
        "crc": {
            "stored": "0x%08x" % stored_crc,
            "expected": "0x%08x" % expected_crc,
            "valid": stored_crc == expected_crc,
        },
        "summary": {
            "tiles": len(tiles),
            "named_features": sum(len(entry["features"]) for entry in tiles),
            "unknown_set_bits": unknown_count,
        },
        "preamble": preamble.describe(raw),
        "tiles": tiles,
        "raw": residual if include_raw else None,
    }


def compare(old_header, old_raw, new_header, new_raw, data_dir, *, include_crc=False):
    """Return semantic named-feature and residual-bit differences."""
    if len(old_header) != 8 or len(new_header) != 8:
        raise agasc.AgascError("comparison requires 8-byte image headers")
    if len(old_raw) != agasc.RAW_LEN or len(new_raw) != agasc.RAW_LEN:
        raise agasc.AgascError("comparison requires 99936-byte raw images")
    by_bit, _ = agasc.load_feature_map(data_dir)
    mapped_masks = agasc._mapped_masks(by_bit)
    added = []
    removed = []
    for (byte, mask), (x, y, feature) in by_bit.items():
        before, after = bool(old_raw[byte] & mask), bool(new_raw[byte] & mask)
        record = {"x": x, "y": y, "feature": feature, "byte": byte, "mask": mask}
        if after and not before:
            added.append(record)
        elif before and not after:
            removed.append(record)
    key = lambda item: (item["x"], item["y"], item["feature"], item["byte"], item["mask"])
    added.sort(key=key)
    removed.sort(key=key)
    raw_changes = []
    limit = agasc.RAW_LEN if include_crc else agasc.CRC_OFFSET
    for offset in range(limit):
        mask = ~mapped_masks[offset] & 0xFF
        before, after = old_raw[offset] & mask, new_raw[offset] & mask
        if before != after:
            raw_changes.append({"offset": offset, "before": before, "after": after})
    old_device, old_max = struct.unpack(">II", old_header)
    new_device, new_max = struct.unpack(">II", new_header)
    return {
        "schema": SCHEMA_VERSION,
        "header": {
            "device": ["0x%08x" % old_device, "0x%08x" % new_device],
            "max_index": ["0x%08x" % old_max, "0x%08x" % new_max],
            "changed": old_header != new_header,
        },
        "summary": {
            "added_features": len(added),
            "removed_features": len(removed),
            "raw_bytes_changed": len(raw_changes),
        },
        "added": added,
        "removed": removed,
        "raw": raw_changes,
    }


def format_description(report):
    lines = []
    if "image" in report:
        lines.append("image %s (%d source byte(s), sha256 %s)" % (
            report["image"]["form"], report["image"]["source_bytes"],
            report["image"]["source_sha256"],
        ))
    lines += [
        "device %s  max_index %s" % (report["device"], report["max_index"]),
        "crc %s (stored %s, expected %s)" % (
            "VALID" if report["crc"]["valid"] else "INVALID",
            report["crc"]["stored"], report["crc"]["expected"],
        ),
        "%d named feature(s) in %d tile(s); %d unmapped set bit(s)" % (
            report["summary"]["named_features"], report["summary"]["tiles"],
            report["summary"]["unknown_set_bits"],
        ),
        "preamble %s (%s)" % (
            report["preamble"]["profile"],
            "generated profile" if report["preamble"]["generated_profile"] else "custom bytes",
        ),
    ]
    for entry in report["tiles"]:
        lines.append("X%dY%d" % (entry["x"], entry["y"]))
        lines.extend("  +" + feature for feature in entry["features"])
    if report["raw"]:
        lines.append("unmapped asserted bytes")
        lines.extend("  0x%06x = 0x%02x" % (entry["offset"], entry["value"])
                     for entry in report["raw"])
    return "\n".join(lines) + "\n"


def format_diff(report):
    lines = []
    if "images" in report:
        lines.append("images %s -> %s" % (
            report["images"]["old"]["form"], report["images"]["new"]["form"]
        ))
    lines += [
        "%d feature(s) added, %d removed; %d unmapped byte(s) changed" % (
            report["summary"]["added_features"], report["summary"]["removed_features"],
            report["summary"]["raw_bytes_changed"],
        )
    ]
    if report["header"]["changed"]:
        lines.append("header changed: device %s -> %s, max_index %s -> %s" % (
            *report["header"]["device"], *report["header"]["max_index"],
        ))
    lines.extend("+ X%dY%d %s" % (item["x"], item["y"], item["feature"])
                 for item in report["added"])
    lines.extend("- X%dY%d %s" % (item["x"], item["y"], item["feature"])
                 for item in report["removed"])
    lines.extend("~ raw[0x%06x] 0x%02x -> 0x%02x" % (
        item["offset"], item["before"], item["after"]
    ) for item in report["raw"])
    return "\n".join(lines) + "\n"
