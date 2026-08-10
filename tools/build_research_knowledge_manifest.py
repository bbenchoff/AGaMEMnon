#!/usr/bin/env python3
"""Build the deterministic inventory for the opt-in research-unsafe profile.

This inventories normalized public chip data. It deliberately does not copy
vendor binaries, routed checkpoints, private paths, or raw workbench dumps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
DEFAULT_OUTPUT = CHIPDB / "research_knowledge_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows(path: Path) -> int | None:
    if path.suffix.lower() != ".csv":
        return None
    with path.open(encoding="utf-8", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    datasets = []
    for path in sorted(CHIPDB.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path == args.output or path.name.startswith("."):
            continue
        row = {
            "path": "agamemnon/chipdb/%s" % path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        count = csv_rows(path)
        if count is not None:
            row["data_rows"] = count
        datasets.append(row)

    payload = {
        "schema": 1,
        "kind": "agamemnon-research-knowledge-manifest",
        "profile": "research-unsafe",
        "warning": (
            "NON-RELEASE: datasets mix independently decoded structure, normalized "
            "vendor-derived observations, silicon tests, enumerated topology, statistical "
            "majorities, conflicts, and predictions. Availability is not qualification."
        ),
        "origin_policy": {
            "vendor_material": (
                "Normalized facts recovered from vendor tools or artifacts are labelled "
                "vendor-derived; they are not represented as independently derived."
            ),
            "raw_material_excluded": (
                "No vendor executable, SDK snapshot, raw route.tx, routed checkpoint, "
                "manual, or private filesystem path is shipped by this manifest."
            ),
            "negative_evidence": (
                "Silicon-dead edges remain hard-blocked under every emission policy."
            ),
        },
        "routing_evidence_classes": {
            "conflict-free-physical-observation": "exact physical selector pair; no observed conflict",
            "unanimous-relative-observation": "tile-relative selector pair unanimous across physical observations",
            "vendor-corpus-context-majority": "complete destination-field selection chosen by corpus majority",
            "vendor-corpus-absolute-majority": "absolute selector pair chosen by corpus majority; conflict not excluded",
            "vendor-corpus-conflicted-majority": "majority pair from a physical edge with two or more preserved observed variants",
            "vendor-corpus-geometric-majority": "geometric selector component chosen by corpus majority",
            "decoded-mesh-template-prediction": "decoded template extrapolation; not an edge-specific observation",
            "trained-selector-prediction": "trained statistical selector prediction",
            "decoded-crossbar-closed-form": "decoded intra-tile crossbar formula",
            "unresolved": "no complete selector encoding; emission still fails unless separately overridden",
        },
        "campaign_context": {
            "r2_frozen_live_rows": 71697,
            "r2_vendor_route_occupancy_witnessed": 71697,
            "r2_unobserved": 0,
            "r2_terminal_phantom": 42297,
            "r2_silicon_dead": 14,
            "qualification_boundary": (
                "An exact vendor-authored route occupancy witness establishes topology use, "
                "not an edge-specific selector encoding or silicon conduction."
            ),
            "source": "AG32-Docs/docs/status/CAMPAIGN_V5_R2_ENDGAME_REPORT.md",
        },
        "datasets": datasets,
    }
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
