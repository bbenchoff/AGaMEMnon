import json
import re
import runpy
from pathlib import Path

import pytest

from agamemnon import cli
from agamemnon.engine.registry import CONSTANTS, OPTIONS, EngineOptions, manifest


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "agamemnon" / "engine"


def test_every_large_engine_environment_switch_is_registered():
    used = set()
    for name in ("arch.py", "bitgen_seq.py"):
        text = (ENGINE / name).read_text(encoding="utf-8")
        used.update(re.findall(r"AGAMEMNON_[A-Z0-9_]+", text))
    assert used <= set(OPTIONS), sorted(used - set(OPTIONS))


def test_registry_evidence_is_repository_local_and_present():
    for name, item in list(OPTIONS.items()) + list(CONSTANTS.items()):
        evidence = item.evidence
        assert not evidence.startswith(("http:", "https:", "C:", "/")), name
        assert (ROOT / evidence).exists(), (name, evidence)


def test_registry_manifest_is_stable_and_complete():
    data = manifest()
    assert [row["name"] for row in data["options"]] == sorted(OPTIONS)
    assert [row["name"] for row in data["constants"]] == sorted(CONSTANTS)
    json.dumps(data, sort_keys=True)


def test_presence_flags_and_typed_values_preserve_legacy_behavior():
    options = EngineOptions({
        "AGAMEMNON_HW_CARRY": "0",
        "AGAMEMNON_NGCLK": "3",
        "AGAMEMNON_SOFT_PENALTY": "1.5",
        "AGAMEMNON_MCU_XY": "10,5",
    })
    assert options.enabled("AGAMEMNON_HW_CARRY")
    assert options.integer("AGAMEMNON_NGCLK") == 3
    assert options.number("AGAMEMNON_SOFT_PENALTY") == pytest.approx(1.5)
    assert options.coordinates("AGAMEMNON_MCU_XY") == (10, 5)
    assert len(options.digest("arch")) == 64


def test_fabric_clock_defaults_to_qualified_10_mhz():
    assert EngineOptions({}).integer("AGAMEMNON_SYSCLK") == 10


def test_bad_coordinate_arity_is_rejected():
    with pytest.raises(ValueError):
        EngineOptions({"AGAMEMNON_MCU_XY": "10"}).coordinates("AGAMEMNON_MCU_XY")


def test_large_engine_modules_are_import_safe_callable_entry_points():
    arch = runpy.run_path(str(ENGINE / "arch.py"), run_name="engine_import_test")
    bitgen = runpy.run_path(str(ENGINE / "bitgen_seq.py"), run_name="engine_import_test")
    assert callable(arch["build_arch"])
    assert callable(bitgen["main"])


def test_cli_manifest_emits_stable_json(tmp_path, capsys):
    output = tmp_path / "manifest.json"
    cli.main(["manifest", "--scope", "arch", "-o", str(output)])
    data = json.loads(output.read_text(encoding="utf-8"))
    assert [row["name"] for row in data["options"]] == sorted(
        name for name, spec in OPTIONS.items() if spec.scope in ("arch", "both")
    )
    assert [row["name"] for row in data["constants"]] == sorted(CONSTANTS)
    assert capsys.readouterr().out == ""
