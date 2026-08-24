#!/usr/bin/env python3
"""Extract conservative routing delays from decoded vendor ``alta_wire.ar``.

The vendor table is indexed by native wire class, driving mux family and
fanout.  The current open graph does not yet carry a proven native class for
every physical wire index, so the emitted ``source_max_ns`` deliberately takes
the maximum WORST value across every class, fanout row, transition and supplied
PVT table for a source family.  This overestimates some paths but never selects
an optimistic class merely from geometry.
"""

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path


FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")
FROM_RE = re.compile(r"FROM\s*:\s*[^:;]*:([^:;]+):[^;]*;")
RESOURCE_RE = re.compile(r"([A-Za-z_]+)(\d+)$")


class ExactWireTimingError(ValueError):
    """A promoted exact-delay table failed its safety contract."""


def normalize_resource(resource):
    """Return the canonical two-digit local resource spelling.

    The release graph mixes historical ``OMUX1`` and canonical ``OMUX01``
    spellings before graph emission. Exact timing keys must not depend on
    which source CSV supplied an otherwise identical edge.
    """
    match = RESOURCE_RE.fullmatch(str(resource))
    if match is None:
        return str(resource)
    return "%s%02d" % (match.group(1), int(match.group(2)))


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_safe_exact(chipdb_root, conservative_omux_ns):
    """Load the certified local exact table or raise before it can be used.

    Callers must catch :class:`ExactWireTimingError` and retain the existing
    conservative family model. A bad or incomplete optional table must never
    turn into an optimistic delay.
    """
    root = Path(chipdb_root)
    table_path = root / "wire_timing_exact_safe.json"
    manifest_path = root / "wire_timing_exact_safe_manifest.json"
    try:
        table = json.loads(table_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExactWireTimingError("exact timing table unavailable or malformed: %s" % exc) from exc

    if table.get("schema") != 1 or manifest.get("schema") != 1:
        raise ExactWireTimingError("unsupported exact timing schema")
    if table.get("units") != "nanoseconds" or manifest.get("units") != "nanoseconds":
        raise ExactWireTimingError("exact timing units are not nanoseconds")
    if manifest.get("table") != table_path.name or manifest.get("table_sha256") != _sha256(table_path):
        raise ExactWireTimingError("exact timing table hash mismatch")
    certification = manifest.get("certification", {})
    if certification.get("under_conservative") is not False:
        raise ExactWireTimingError("exact timing batch lacks a non-optimistic certification")

    expected = certification.get("public_matched_pairs")
    entries = table.get("entries")
    if not isinstance(entries, list) or expected != len(entries):
        raise ExactWireTimingError("exact timing entry denominator mismatch")
    decoded_max = float(certification.get("decoded_slow_max_ns", -1.0))
    if not math.isfinite(decoded_max) or decoded_max < 0.0:
        raise ExactWireTimingError("invalid certified decoded delay")
    if decoded_max > float(conservative_omux_ns):
        raise ExactWireTimingError("decoded delay exceeds its conservative comparison bound")

    exact = {}
    for entry in entries:
        source = normalize_resource(entry.get("src", ""))
        destination = normalize_resource(entry.get("dst", ""))
        delay = float(entry.get("slow_max_ns", -1.0))
        if not re.fullmatch(r"OMUX\d{2}", source) or not re.fullmatch(r"IMUX\d{2}", destination):
            raise ExactWireTimingError("exact timing entry is outside the certified OMUX->IMUX pattern")
        if not math.isfinite(delay) or delay != decoded_max:
            raise ExactWireTimingError("exact timing entry differs from its certified pattern delay")
        key = (source, destination)
        if key in exact:
            raise ExactWireTimingError("duplicate exact timing key %s>%s" % key)
        exact[key] = delay
    return exact


def exact_delay_ns(exact, source_resource, destination_resource):
    """Look up a normalized exact edge without inferring missing entries."""
    return exact.get((normalize_resource(source_resource), normalize_resource(destination_resource)))


def select_routing_delay_ns(exact, source_resource, destination_resource,
                            conservative_ns, margin=1.0):
    """Choose certified exact or conservative fallback, with one safety margin."""
    value = exact_delay_ns(exact, source_resource, destination_resource)
    if value is None:
        value = float(conservative_ns)
    return value * max(1.0, float(margin))


class MeasuredWireTimingError(ValueError):
    """A promoted measured per-family delay table failed its safety contract."""


# Families this project holds direct STA-derived evidence for (AG32-Docs
# tools/wire_timing_fit, NNLS fit against reference-backend setup.rpt, R^2=0.995,
# one design/one part/one PVT corner). This tuple is the actual gate: a row
# in wire_timing_measured.json for any OTHER family has no effect until this
# list is deliberately extended by a person, so widening which families may
# override the worst-case table is a code change, not a data-only edit.
# Families left out on purpose and why (see wire_timing_fit_results.json):
#   OMUX/IMUX      -- collinear (corr=0.99), the split is not identifiable
#   SeamMUX/TileClkMUX -- collinear (corr=1.00)
#   PllClkInMUX, InputMUX -- n=1 equation
#   (62 more)      -- zero observations
MEASURED_FAMILIES = ("RMUX", "ClkMUX", "BufMUX")


def load_measured_families(chipdb_root, worst_source):
    """Load the certified measured per-family delay table, or raise before use.

    Mirrors :func:`load_safe_exact`'s fail-closed shape: callers must catch
    :class:`MeasuredWireTimingError` and keep the existing conservative
    worst-case model.  A bad, incomplete, or suspiciously-not-conservative
    table must never silently become an optimistic delay.

    ``worst_source`` is the already-loaded ``source_max_ns`` mapping from
    ``wire_timing_worst.json``; every measured family is required to be
    strictly cheaper than its worst-case charge, since the entire point of
    this table is to replace an over-charge with evidence, not to introduce
    an unrelated number under the same name.
    """
    path = Path(chipdb_root) / "wire_timing_measured.json"
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MeasuredWireTimingError(
            "measured wire timing table unavailable or malformed: %s" % exc) from exc
    if table.get("schema") != 1:
        raise MeasuredWireTimingError("unsupported measured wire timing schema")
    if table.get("units") != "nanoseconds":
        raise MeasuredWireTimingError("measured wire timing units are not nanoseconds")
    families = table.get("families_ns")
    if not isinstance(families, dict) or not families:
        raise MeasuredWireTimingError("measured wire timing table has no families_ns")

    measured = {}
    for family in MEASURED_FAMILIES:
        if family not in families:
            continue
        value = families[family]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0.0):
            raise MeasuredWireTimingError(
                "measured delay for %s is not a positive finite number" % family)
        worst = worst_source.get(family)
        if worst is not None and float(value) >= float(worst):
            raise MeasuredWireTimingError(
                "measured delay for %s (%.4g ns) is not below its worst-case "
                "charge (%.4g ns); refusing to treat a non-improvement as "
                "measured evidence" % (family, value, worst))
        measured[family] = float(value)
    return measured


def parse_wire_timing(text):
    """Return ``{wire_class: {source_family: worst_ns}}`` from decoded text."""
    result = {}
    wire_class = source_family = None
    in_worst = False
    found_worst = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("WIRE "):
            wire_class = line.split(None, 1)[1]
            result.setdefault(wire_class, {})
            source_family = None
            in_worst = False
            continue
        match = FROM_RE.fullmatch(line)
        if match:
            source_family = match.group(1)
            continue
        if line == "TABLE WORST":
            if wire_class is None or source_family is None:
                raise ValueError("WORST table lacks WIRE/FROM context")
            in_worst = True
            found_worst = True
            continue
        if line == "END_TABLE":
            in_worst = False
            continue
        if not in_worst:
            continue
        values = [float(value) for value in FLOAT_RE.findall(line)]
        if not values:
            continue
        worst = max(values)
        old = result[wire_class].get(source_family)
        result[wire_class][source_family] = worst if old is None else max(old, worst)
    if not found_worst:
        raise ValueError("no TABLE WORST data found")
    return result


def aggregate(paths):
    classes = {}
    inputs = []
    for path in paths:
        payload = open(path, "rb").read()
        parsed = parse_wire_timing(payload.decode("utf-8"))
        inputs.append({"name": os.path.basename(path),
                       "sha256": hashlib.sha256(payload).hexdigest()})
        for wire_class, families in parsed.items():
            out = classes.setdefault(wire_class, {})
            for family, delay in families.items():
                out[family] = max(out.get(family, 0.0), delay)
    source_max = {}
    for families in classes.values():
        for family, delay in families.items():
            source_max[family] = max(source_max.get(family, 0.0), delay)
    if not source_max:
        raise ValueError("no routing delay records found")
    return {
        "schema": 1,
        "aggregation": "max of every WORST transition and fanout row across all supplied wire classes and PVT tables",
        "inputs": sorted(inputs, key=lambda item: item["name"]),
        "classes": {key: dict(sorted(value.items())) for key, value in sorted(classes.items())},
        "source_max_ns": dict(sorted(source_max.items())),
        "fallback_max_ns": max(source_max.values()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="decoded *_alta_wire.ar.txt files")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)
    result = aggregate(args.inputs)
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print("wire timing: %d input(s), %d classes, %d source families, fallback %.3f ns" %
          (len(result["inputs"]), len(result["classes"]), len(result["source_max_ns"]),
           result["fallback_max_ns"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
