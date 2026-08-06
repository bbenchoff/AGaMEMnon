from pathlib import Path

import pytest

from agamemnon.engine.features import CHIPDB_OWNERS, FEATURES, validate_features
from agamemnon.engine.features.protocol import (
    EmissionPhase,
    FeatureDescriptor,
    WritableRegion,
)


ROOT = Path(__file__).resolve().parents[1]


def test_route_through_is_the_first_declared_feature():
    assert [feature.descriptor.feature_id for feature in FEATURES] == ["route_through"]
    descriptor = FEATURES[0].descriptor
    assert descriptor.phase is EmissionPhase.ROUTING
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == ("route_through_footprints.csv",)
    assert CHIPDB_OWNERS == {"route_through_footprints.csv": "route_through"}
    assert (ROOT / "agamemnon" / "chipdb" / descriptor.chipdb_files[0]).is_file()
    assert descriptor.writable_regions == (WritableRegion(
        kind="sparse_table",
        source="route_through_footprints.csv",
        byte_field="byte",
        mask_field="write_mask",
    ),)


def test_feature_registry_rejects_duplicate_chipdb_ownership():
    class Duplicate:
        descriptor = FeatureDescriptor(
            feature_id="duplicate",
            options=(),
            chipdb_files=("route_through_footprints.csv",),
            writable_regions=(),
            phase=EmissionPhase.ROUTING,
            evidence=("qualification/bram_evidence.jsonl",),
            maturity="diagnostic",
            architecture="none",
            bitstream="none",
        )

        def add_architecture(self, context):
            return None

        def emit_bitstream(self, context):
            return 0

    with pytest.raises(ValueError, match="owned by both"):
        validate_features(FEATURES + (Duplicate(),))
