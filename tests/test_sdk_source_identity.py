"""The independent archive oracle must track the hardware-qualified source image."""
import json
from pathlib import Path
import runpy

from agamemnon.cli import QUALIFIED_ROUTE_PROFILES


def test_archive_source_pins_match_cli_and_paired_silicon_evidence():
    root = Path(__file__).resolve().parents[1]
    smoke = runpy.run_path(str(root / "tools/bundle/smoke_archive.py"))
    profile = smoke["BRAM_SOURCE_PROFILE"]
    evidence = json.loads((root / "qualification" /
        "registered_bram_tmux9_source_selector_silicon.json").read_text())
    assert evidence["silicon_status"] == "PAIRED_RESEARCH_PASS_BOUNDED"
    witnessed = evidence["profiles"][profile]
    pinned = QUALIFIED_ROUTE_PROFILES[profile]
    assert smoke["BRAM_SOURCE_HASHES"] == {
        "raw": witnessed["raw_sha256"], "compressed": witnessed["compressed_sha256"]}
    assert smoke["BRAM_SOURCE_HASHES"] == {
        "raw": pinned["source_build_bitstream_sha256"],
        "compressed": pinned["source_build_compressed_sha256"]}
