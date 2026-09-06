import copy
import json

import pytest

from agamemnon.cli import _normalize_synthesized_top


def test_custom_top_retains_logic_and_libraries(tmp_path):
    module = {"attributes": {"top": "1", "src": "user.v:1"},
              "cells": {"state": {"type": "DFF", "connections": {"Q": [3], "D": [4]}}},
              "ports": {"out": {"direction": "output", "bits": [3]}}}
    library = {"attributes": {"blackbox": "1"}, "ports": {}}
    original = {"modules": {"application": module, "DFF": library}}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(original))
    assert _normalize_synthesized_top(path, "application") == "top"
    output = json.loads(path.read_text())
    assert output == {"modules": {"top": module, "DFF": library}}
    before = path.read_bytes()
    assert _normalize_synthesized_top(path) == "top"
    assert path.read_bytes() == before


@pytest.mark.parametrize("fault", ["collision", "wrong_selected", "multiple_tops"])
def test_ambiguous_or_wrong_top_fails_without_mutation(tmp_path, fault):
    module = {"attributes": {"top": "1"}, "cells": {}}
    document = {"modules": {"application": copy.deepcopy(module)}}
    if fault == "collision":
        document["modules"]["top"] = {"attributes": {"blackbox": "1"}}
    if fault == "multiple_tops":
        document["modules"]["second"] = copy.deepcopy(module)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        _normalize_synthesized_top(path, "different" if fault == "wrong_selected" else "application")
    assert path.read_bytes() == before
