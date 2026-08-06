import ast
import json
import re
import runpy
from pathlib import Path

import pytest

from agamemnon import cli
from agamemnon.engine.bitgen import EMISSION_PHASES
from agamemnon.engine.features.protocol import EmissionPhase
from agamemnon.engine.registry import CONSTANTS, OPTIONS, EngineOptions, manifest


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "agamemnon" / "engine"
OPTION_ACCESSORS = {"enabled", "raw", "integer", "number", "coordinates"}

# Every temporary exception must map an option name to a one-line reason.
UNCONSUMED_OPTION_ALLOWLIST = {}


def _is_os_environ(node):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr == "environ"
    )


def _consumed_options():
    used = set()
    for path in (ROOT / "agamemnon").rglob("*.py"):
        if path == ENGINE / "registry.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                name = node.args[0]
                if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr in OPTION_ACCESSORS or (
                    func.attr == "get" and _is_os_environ(func.value)
                ):
                    used.add(name.value)
            elif isinstance(node, ast.Subscript) and _is_os_environ(node.value):
                name = node.slice
                if isinstance(name, ast.Constant) and isinstance(name.value, str):
                    used.add(name.value)
    for suffix in ("*.c", "*.cc", "*.cpp", "*.h", "*.hpp"):
        for path in (ROOT / "agamemnon").rglob(suffix):
            text = path.read_text(encoding="utf-8")
            used.update(re.findall(r'(?:std::)?getenv\(\s*"(AGAMEMNON_[A-Z0-9_]+)"', text))
    return used


def test_every_large_engine_environment_switch_is_registered():
    used = set()
    for name in ("archgen.py", "bitgen.py"):
        text = (ENGINE / name).read_text(encoding="utf-8")
        used.update(re.findall(r"AGAMEMNON_[A-Z0-9_]+", text))
    assert used <= set(OPTIONS), sorted(used - set(OPTIONS))


def test_every_registered_option_is_consumed():
    assert all(reason.strip() for reason in UNCONSUMED_OPTION_ALLOWLIST.values())
    missing = set(OPTIONS) - _consumed_options() - set(UNCONSUMED_OPTION_ALLOWLIST)
    assert not missing, sorted(missing)


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
    archgen = runpy.run_path(
        str(ENGINE / "archgen.py"), run_name="engine_import_test"
    )
    bitgen = runpy.run_path(str(ENGINE / "bitgen.py"), run_name="engine_import_test")
    bitgen_shim = runpy.run_path(
        str(ENGINE / "bitgen_seq.py"), run_name="engine_import_test"
    )
    assert callable(arch["build"])
    assert callable(archgen["build"])
    assert callable(bitgen["main"])
    assert callable(bitgen_shim["main"])


def test_nextpnr_arch_entry_is_only_an_injected_global_shim():
    source = (ENGINE / "arch.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 10
    assert "from agamemnon.engine.archgen import build" in source
    assert 'if "ctx" in globals() and "Loc" in globals()' in source
    assert "build(ctx, Loc)" in source


def test_bitgen_seq_entry_is_only_a_compatibility_shim():
    source = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 10
    assert "from agamemnon.engine.bitgen import main" in source
    assert 'if __name__ == "__main__"' in source


def test_bitgen_driver_names_every_emission_phase_and_owns_no_chipdb_table():
    assert EMISSION_PHASES == (
        EmissionPhase.CLEAR_BASELINE,
        EmissionPhase.ROUTING,
        EmissionPhase.MCU_EDGES,
        EmissionPhase.LOGIC,
        EmissionPhase.CLOCKS,
        EmissionPhase.IO,
        EmissionPhase.BRAM,
        EmissionPhase.PREAMBLE,
        EmissionPhase.INTEGRITY,
    )
    source = (ENGINE / "bitgen.py").read_text(encoding="utf-8")
    assert ".csv" not in source
    assert "def prepare_design" in source
    assert "def clear_baseline_phase" in source
    assert "def emit_feature_phases" in source
    assert "def emit_preamble_phase" in source
    assert "def emit_integrity_phase" in source


def test_cli_manifest_emits_stable_json(tmp_path, capsys):
    output = tmp_path / "manifest.json"
    cli.main(["manifest", "--scope", "arch", "-o", str(output)])
    data = json.loads(output.read_text(encoding="utf-8"))
    assert [row["name"] for row in data["options"]] == sorted(
        name for name, spec in OPTIONS.items() if spec.scope in ("arch", "both")
    )
    assert [row["name"] for row in data["constants"]] == sorted(CONSTANTS)
    assert capsys.readouterr().out == ""
