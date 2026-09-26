"""Async resources follow the synthesized control, not names or plain enables."""
import json

import pytest

from agamemnon.cli import _json_uses_async_clear


@pytest.mark.parametrize("cells,expected", [
    ({}, False),
    ({"async_reset": {"type": "DFF"}}, False),
    ({"enabled": {"type": "DFFE"}}, False),
    ({"ordinary": {"type": "DFF"}, "clear": {"type": "$_DFF_PP0_"}}, True),
    ({"control": {"type": "AGRV2K_TILE_CONTROL", "attributes": {
        "AGRV2K_SHARED_CONTROL_MODE": "ASYNC_CLEAR_POS_ZERO"}}}, True),
    ({"control": {"type": "AGRV2K_TILE_CONTROL", "attributes": {
        "AGRV2K_SHARED_CONTROL_MODE": "CLOCK_ENABLE_POS"}}}, False),
])
def test_typed_async_graph_demand(tmp_path, cells, expected):
    path = tmp_path / "synth.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": cells}}}))
    assert _json_uses_async_clear(path) is expected
