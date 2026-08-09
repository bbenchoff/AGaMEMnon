#!/usr/bin/env python3
"""Import the reviewed vendor-free R1-BRAM admission export compactly."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SOURCE_SHA256 = "1c7f6edc86bf0caf8f6abfc1356d00770c34aae0f8e17c7962e3bd129ae6d628"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compact(source: Path) -> dict:
    raw = source.read_bytes()
    if sha256_bytes(raw) != SOURCE_SHA256:
        raise ValueError("public B4 admission export hash mismatch")
    value = json.loads(raw)
    if (value.get("schema") != "agamemnon.experimental-bram-config-admission.v1"
            or value.get("status") != "review-only"
            or value.get("claim") != "config-encoding-only"
            or value.get("accounting") != {
                "admitted_rows": 39,
                "execution_exclusions": 0,
                "preexisting_exceptions": 15,
            }
            or value.get("permission") != {
                "allowed": "experimental-strict",
                "default_selection": "denied",
                "release_strict": "denied",
            }):
        raise ValueError("public B4 admission export contract mismatch")
    rows = []
    for row in value["rows"]:
        selectors = row["physical_mux_selectors"]
        encoded = json.dumps(selectors, separators=(",", ":")).encode("utf-8")
        compact_row = {
            key: row[key] for key in (
                "target_id", "name", "parameter", "legal_value",
                "registry_maturity", "evidence_tier", "claim_domain",
                "strict_permission", "scope",
            )
        }
        compact_row.update({
            "selector_count": len(selectors),
            "selector_set_sha256": sha256_bytes(encoded),
        })
        if len(selectors) <= 16:
            compact_row["physical_mux_selectors"] = selectors
        else:
            compact_row["selector_representation"] = "explicit-set-digest"
        rows.append(compact_row)
    if len(rows) != 39 or len({row["target_id"] for row in rows}) != 39:
        raise ValueError("public B4 export does not contain 39 unique rows")
    return {
        "schema": "agamemnon.bram-config-encoding-metadata.v1",
        "status": "experimental-review",
        "claim": "config-encoding-only",
        "source_admission_manifest_sha256": SOURCE_SHA256,
        "provenance": value["provenance"],
        "accounting": value["accounting"],
        "permission": value["permission"],
        "rows": rows,
        "non_claim": value["non_claim"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    value = compact(args.source)
    if args.output.exists():
        raise SystemExit("refusing to overwrite %s" % args.output)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps({"rows": len(value["rows"]),
                      "sha256": sha256_bytes(args.output.read_bytes())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
