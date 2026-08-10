import csv
import hashlib
import json
from pathlib import Path

from agamemnon.engine import chipdb_schema
from agamemnon.engine.bitgen import verify_research_knowledge_manifest
from agamemnon.engine.features.routing import RoutingSelectorTables
from agamemnon.engine.registry import options_from


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def test_research_manifest_binds_every_public_chipdb_dataset():
    manifest_path = CHIPDB / "research_knowledge_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["profile"] == "research-unsafe"
    assert "vendor-derived" in manifest["warning"]
    assert manifest["campaign_context"] == {
        "qualification_boundary": (
            "An exact vendor-authored route occupancy witness establishes topology use, "
            "not an edge-specific selector encoding or silicon conduction."
        ),
        "r2_frozen_live_rows": 71697,
        "r2_silicon_dead": 14,
        "r2_terminal_phantom": 42297,
        "r2_unobserved": 0,
        "r2_vendor_route_occupancy_witnessed": 71697,
        "source": "AG32-Docs/docs/status/CAMPAIGN_V5_R2_ENDGAME_REPORT.md",
    }
    rows = {Path(row["path"]).name: row for row in manifest["datasets"]}
    expected = {
        path.name for path in CHIPDB.iterdir()
        if path.is_file() and path != manifest_path and not path.name.startswith(".")
    }
    assert set(rows) == expected
    for name, row in rows.items():
        path = CHIPDB / name
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert row["bytes"] == path.stat().st_size
        if path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as stream:
                assert row["data_rows"] == sum(1 for _ in csv.DictReader(stream))


def test_research_manifest_records_hard_negative_boundary():
    manifest = json.loads(
        (CHIPDB / "research_knowledge_manifest.json").read_text(encoding="utf-8")
    )
    assert "hard-blocked" in manifest["origin_policy"]["negative_evidence"]
    assert "raw route.tx" in manifest["origin_policy"]["raw_material_excluded"]


def test_conflict_atlas_preserves_vendor_derived_disagreement():
    datasets, metadata = chipdb_schema.load(
        str(CHIPDB / "selector_conflict_atlas.agdb"),
        expected=("conflicted_edge",),
    )
    rows = datasets["conflicted_edge"]
    assert len(rows) == metadata["conflicted_physical_keys"] == 74103
    assert metadata["observed_physical_keys"] == 733862
    assert metadata["origin"] == "vendor-derived-normalized-selector-observations"
    assert metadata["source_sha256"] == (
        "5ef77c5312a4997d009d78b3c72f56d3e66c7ac70610c7032550682ae720f044"
    )
    for majority_pair, majority_count, samples, variants in rows.values():
        assert len(variants) >= 2
        assert variants[0] == (majority_pair, majority_count)
        assert samples == sum(count for _pair, count in variants)


def test_research_runtime_loads_conflicts_but_release_does_not():
    release = RoutingSelectorTables.load(CHIPDB, options_from({}))
    assert release.conflicted_edge == {}
    research = RoutingSelectorTables.load(CHIPDB, options_from({
        "AGAMEMNON_STRICT_POLICY": "research-unsafe",
        "AGAMEMNON_RESEARCH_UNSAFE": "1",
    }))
    assert len(research.conflicted_edge) == 74103


def test_research_manifest_runtime_verification_detects_tampering(tmp_path):
    assert len(verify_research_knowledge_manifest(CHIPDB)) == 64
    fake = tmp_path / "chipdb"
    fake.mkdir()
    manifest = json.loads(
        (CHIPDB / "research_knowledge_manifest.json").read_text(encoding="utf-8")
    )
    row = manifest["datasets"][0]
    (fake / Path(row["path"]).name).write_bytes(b"tampered")
    (fake / "research_knowledge_manifest.json").write_text(
        json.dumps({**manifest, "datasets": [row]}), encoding="utf-8"
    )
    try:
        verify_research_knowledge_manifest(fake)
    except SystemExit as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered research dataset was accepted")
