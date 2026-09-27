"""Positioned topology exclusions survive positive occupancy and wider admission."""
import csv
from pathlib import Path

import pytest

from devdb_fixtures import DatabaseFixtures
from agamemnon.engine.features.routing import FEATURE, RoutingSelectorTables
from agamemnon.engine.features.physical_io import PhysicalIoState
from agamemnon.engine.registry import EngineOptions


@pytest.fixture(scope="module")
def selector_tables():
    return RoutingSelectorTables.load(
        Path(__file__).resolve().parents[1] / "agamemnon/chipdb", EngineOptions({}))


@pytest.mark.parametrize("pip", [
    "X11Y4_RMUX09.X11Y4_RMUX38", "X11Y4_RMUX9.X11Y4_RMUX38",
    "X15Y3_RMUX14.X15Y4_RMUX61",
])
@pytest.mark.parametrize("environment", [
    {}, {"AGAMEMNON_ROUTING_ADMISSION": "tiered"},
    {"AGAMEMNON_ALLOW_UNMAPPED": "1"}, {"AGAMEMNON_RESEARCH_UNSAFE": "1"},
])
def test_direct_pack_rejects_unsupported_selector_before_fallback(
        selector_tables, pip, environment):
    with pytest.raises(SystemExit, match="unsupported positioned selector: " + pip):
        FEATURE.prepare(
            pips=[pip], cell={}, options=EngineOptions(environment),
            tables=selector_tables, physical_io_state=PhysicalIoState(),
            exact_mcu_pips={}, mcu_cells={}, mcu_exit_pairs={},
            bram_feature=None, bram_state=None, slice_config={},
            left_vendor_slices=set(), retained_withdrawn_pips={pip})


@pytest.fixture(scope="module")
def graphs():
    fixtures = DatabaseFixtures()
    try:
        paths = {profile: fixtures.path(profile) for profile in ("strict", "tiered")}
        fixtures.prepare()
        yield {profile: {row["name"] for row in csv.DictReader((path / "dev_pips.csv").open())}
               for profile, path in paths.items()}
    finally:
        fixtures.close()


@pytest.mark.parametrize("profile", ["strict", "tiered"])
def test_unresolved_inputs_are_excluded_without_removing_calibrated_neighbors(graphs, profile):
    pips = graphs[profile]
    assert "X11Y4_RMUX09.X11Y4_RMUX38" not in pips
    assert "X15Y3_RMUX14.X15Y4_RMUX61" not in pips
    # Twenty independently resolved input selections at these exact muxes.
    # Preserve spatial scope: adjacent rows and other source families remain.
    neighbors = {
        "X11Y4_RMUX38": ["X12Y4_RMUX33", "X11Y1_RMUX09", "X11Y2_RMUX09",
                         "X11Y3_RMUX09", "X7Y4_RMUX81", "X9Y4_RMUX81", "X10Y4_RMUX81"],
        "X15Y4_RMUX61": ["X11Y4_RMUX38", "X12Y4_RMUX38", "X13Y4_RMUX38", "X14Y4_RMUX38",
                         "X16Y4_RMUX86", "X17Y4_RMUX86", "X15Y1_RMUX62", "X15Y2_RMUX62",
                         "X15Y3_RMUX62", "X15Y5_RMUX14", "X15Y6_RMUX14", "X15Y7_RMUX14",
                         "X15Y8_RMUX14"],
    }
    expected = {source + "." + destination for destination, sources in neighbors.items() for source in sources}
    assert expected <= pips, sorted(expected - pips)
