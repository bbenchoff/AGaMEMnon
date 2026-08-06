from pathlib import Path

import pytest

from agamemnon.engine.features import CHIPDB_OWNERS, FEATURES, validate_features
from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
from agamemnon.engine.features.mcu_ahb import (
    EXACT_PIP_CFG_FILES,
    FEATURE as MCU_AHB_FEATURE,
)
from agamemnon.engine.features.protocol import (
    BitstreamContext,
    EmissionPhase,
    FeatureDescriptor,
    WritableRegion,
)


ROOT = Path(__file__).resolve().parents[1]


def test_route_through_is_the_first_declared_feature():
    assert [feature.descriptor.feature_id for feature in FEATURES] == [
        "route_through", "bram", "mcu_ahb", "carry",
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
    assert CHIPDB_OWNERS["slice_cfg.csv"] == "carry"
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


def test_carry_feature_owns_slice_selectors_and_emission():
    descriptor = CARRY_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.LOGIC
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == ("slice_cfg.csv",)
    assert descriptor.writable_regions == (WritableRegion(
        kind="selector_table",
        source="slice_cfg.csv",
        byte_field="byte",
        mask_field="mask",
    ),)

    fields = CARRY_FEATURE.load_slice_config(ROOT / "agamemnon" / "chipdb")
    module = {"cells": {
        "seed": {
            "type": "GENERIC_SLICE",
            "attributes": {"NEXTPNR_BEL": "X20Y12_SLICE0"},
            "parameters": {},
            "connections": {"COUT": [10]},
        },
        "bit0": {
            "type": "GENERIC_SLICE",
            "attributes": {"NEXTPNR_BEL": "X20Y12_SLICE1"},
            "parameters": {"BYPASSEN": "1"},
            "connections": {"CIN": [10], "COUT": [11]},
        },
    }}
    state = CARRY_FEATURE.prepare(module, fields)
    assert len(state.clears) == 8
    assert state.sets == [
        fields[(20, 12, "CFG_LUTCMUX[1]")],
        fields[(20, 12, "CFG_LUTCMUX[3]")],
        fields[(20, 12, "CFG_BYPASSEN[1]")],
    ]
    image = bytearray([0xFF]) * (max(byte for byte, _ in state.clears) + 1)
    context = BitstreamContext(
        image=image,
        module=module,
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=None,
        state=state,
    )
    assert CARRY_FEATURE.clear_bitstream(context) == 8
    assert CARRY_FEATURE.emit_bitstream(context) == 3
    for byte, mask in set(state.clears) - set(state.sets):
        assert image[byte] & mask == 0
    for byte, mask in state.sets:
        assert image[byte] & mask == mask
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(
        encoding="utf-8"
    )
    assert "CARRY_FEATURE.load_slice_config" in bitgen
    assert "CARRY_FEATURE.clear_bitstream" in bitgen
    assert "CARRY_FEATURE.emit_bitstream" in bitgen
