import copy
import json
from pathlib import Path

import pytest

from agamemnon.engine.crossbar_outputs import MODEL_ATTRIBUTE, source_modes


def design(port="F", pip="X14Y8_OMUX04.X14Y8_IMUX09"):
    return {"cells": {"source": {"type": "GENERIC_SLICE",
        "attributes": {MODEL_ATTRIBUTE: "1", "NEXTPNR_BEL": "X14Y8_SLICE1"},
        "connections": {port: [20]}}},
        "netnames": {"data": {"bits": [20], "attributes": {"ROUTING": pip}}}}


@pytest.mark.parametrize("port,expected", [("F", 0), ("Q", 1)])
@pytest.mark.parametrize("pip", ["X14Y8_OMUX04.X14Y8_IMUX09",
                                "X14Y8_OMUX05.X14Y8_OMUX04"])
def test_direct_and_bridge_source_modes_follow_the_actual_output(port, expected, pip):
    assert source_modes(design(port, pip)) == {(14, 8, 1): expected}


def test_two_distinct_sources_cannot_select_one_lane_differently():
    module = design()
    module["cells"]["source"]["connections"]["Q"] = [21]
    module["netnames"]["q"] = {"bits": [21], "attributes": {
        "ROUTING": "X14Y8_OMUX05.X14Y8_OMUX04"}}
    with pytest.raises(ValueError, match="F and Q compete"):
        source_modes(module)


def test_foreign_signal_cannot_claim_a_typed_presentation():
    module = design()
    module["netnames"]["data"]["bits"] = [999]
    with pytest.raises(ValueError, match="matching typed source"):
        source_modes(module)


def test_native_string_marker_keeps_source_typed_encoding():
    module = design()
    module["cells"]["source"]["attributes"][MODEL_ATTRIBUTE] = "1 "
    assert source_modes(module) == {(14, 8, 1): 0}


@pytest.mark.parametrize("marker", ["0", "0 ", "10", "true", ""])
def test_other_markers_do_not_enable_the_model(marker):
    module = design()
    module["cells"]["source"]["attributes"][MODEL_ATTRIBUTE] = marker
    assert source_modes(module) == {}


def test_legacy_checkpoints_do_not_change_encoding():
    root = Path(__file__).resolve().parents[1]
    artifacts = json.loads((root / "qualification/pack_regression.json").read_text())["artifacts"]
    assert len(artifacts) >= 58
    for artifact in artifacts:
        routed = json.loads((root / artifact["routed"]).read_text())
        for module in routed["modules"].values():
            assert source_modes(module) == {}, artifact["routed"]
