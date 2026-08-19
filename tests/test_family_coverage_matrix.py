"""AG32 family coverage matrix (T25, docs/FAMILY_COVERAGE_MATRIX.md) tests.

The matrix data (agamemnon/sdk/family_coverage_matrix.json) is the single
source of truth; docs/FAMILY_COVERAGE_MATRIX.md is regenerated from it by
tools/generate_family_coverage_matrix.py. These tests pin the "never claim
silicon-qualified without an evidence record" invariant and keep the
generated doc from drifting.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from generate_family_coverage_matrix import (  # noqa: E402
    VALID_TIERS,
    load_matrix,
    validate_matrix,
)
from agamemnon.engine import family  # noqa: E402


def test_generated_family_coverage_doc_is_current():
    subprocess.run(
        [sys.executable, "tools/generate_family_coverage_matrix.py", "--check"],
        cwd=ROOT,
        check=True,
    )


def test_matrix_validates_against_the_family_registry():
    validate_matrix(load_matrix())


def test_matrix_covers_every_part_and_surface_exactly():
    data = load_matrix()
    assert set(data["parts"]) == set(family.PART_NAMES)
    for part_name, part_data in data["parts"].items():
        assert set(part_data["cells"]) == set(data["surfaces"])


def test_every_cell_uses_a_valid_tier_with_a_note_and_evidence_list():
    data = load_matrix()
    for part_name, part_data in data["parts"].items():
        for surface, cell in part_data["cells"].items():
            assert cell["tier"] in VALID_TIERS, (part_name, surface)
            assert cell["note"], (part_name, surface)
            assert isinstance(cell["evidence"], list), (part_name, surface)


def test_only_the_qualified_dev_board_is_silicon_qualified_anywhere():
    """Never-wrong backstop: no part may claim silicon-qualified without a recorded board."""
    data = load_matrix()
    for part_name, part_data in data["parts"].items():
        part = family.get_part(part_name)
        silicon_qualified_cells = [
            surface for surface, cell in part_data["cells"].items()
            if cell["tier"] == "silicon-qualified"
        ]
        if silicon_qualified_cells:
            assert part.has_qualified_board, (part_name, silicon_qualified_cells)
    # And pin the exact current state: only the reference dev board has any
    # silicon-qualified cell today. This assertion is meant to force a
    # deliberate review (not a silent drift) the day a second part earns one.
    qualified_parts = {
        name for name, part_data in data["parts"].items()
        if any(cell["tier"] == "silicon-qualified" for cell in part_data["cells"].values())
    }
    assert qualified_parts == {"AG32VF303CCT6"}


def test_psram_tier_is_never_recorded_as_silicon_qualified_or_build_supported():
    """No PSRAM decode work exists yet anywhere in the family (see the goal doc)."""
    data = load_matrix()
    for part_name, part_data in data["parts"].items():
        tier = part_data["cells"]["psram"]["tier"]
        assert tier in ("n/a", "recovered-only"), (part_name, tier)


@pytest.mark.parametrize("surface", ["pad_out", "pad_in", "oe"])
def test_electrical_surfaces_are_never_transferred_off_the_qualified_part(surface):
    """Matches claim_policy: physical/electrical claims never auto-transfer by package."""
    data = load_matrix()
    for part_name, part_data in data["parts"].items():
        tier = part_data["cells"][surface]["tier"]
        if part_name != "AG32VF303CCT6":
            assert tier != "silicon-qualified", (part_name, surface)
