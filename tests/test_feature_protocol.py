from pathlib import Path

import pytest

from agamemnon.engine.features import CHIPDB_OWNERS, FEATURES, validate_features
from agamemnon.engine.features.mcu_ahb import (
    EXACT_PIP_CFG_FILES,
    FEATURE as MCU_AHB_FEATURE,
)
from agamemnon.engine.features.protocol import (
    EmissionPhase,
    FeatureDescriptor,
    WritableRegion,
)


ROOT = Path(__file__).resolve().parents[1]


def test_route_through_is_the_first_declared_feature():
    assert [feature.descriptor.feature_id for feature in FEATURES] == [
        "route_through", "bram", "mcu_ahb",
    ]
    descriptor = FEATURES[0].descriptor
    assert descriptor.phase is EmissionPhase.ROUTING
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == ("route_through_footprints.csv",)
    assert CHIPDB_OWNERS["route_through_footprints.csv"] == "route_through"
    assert (ROOT / "agamemnon" / "chipdb" / descriptor.chipdb_files[0]).is_file()
    assert descriptor.writable_regions == (WritableRegion(
        kind="sparse_table",
        source="route_through_footprints.csv",
        byte_field="byte",
        mask_field="write_mask",
    ),)
    assert CHIPDB_OWNERS["bram_resolver.json"] == "bram"
    assert CHIPDB_OWNERS["mcu_ahb32_pip_cfg.csv"] == "mcu_ahb"
    for feature in FEATURES:
        for filename in feature.descriptor.chipdb_files:
            assert (ROOT / "agamemnon" / "chipdb" / filename).is_file()


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

        def clear_bitstream(self, context):
            return 0

        def emit_bitstream(self, context):
            return 0

    with pytest.raises(ValueError, match="owned by both"):
        validate_features(FEATURES + (Duplicate(),))


def test_mcu_ahb_feature_owns_exact_selector_loading():
    descriptor = MCU_AHB_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.MCU_EDGES
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files[:len(EXACT_PIP_CFG_FILES)] == EXACT_PIP_CFG_FILES
    assert descriptor.writable_regions == tuple(
        WritableRegion(kind="selector_table", source=filename)
        for filename in EXACT_PIP_CFG_FILES
    )
    fields = MCU_AHB_FEATURE.load_exact_pip_fields(
        ROOT / "agamemnon" / "chipdb"
    )
    assert len(fields) == 257
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(
        encoding="utf-8"
    )
    assert "MCU_AHB_FEATURE.load_exact_pip_fields" in bitgen
    assert '"mcu_ahb32_pip_cfg.csv"' not in bitgen
