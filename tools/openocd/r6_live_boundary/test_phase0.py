from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.openocd.r6_live_boundary.audit import (
    AuditFailure,
    derive_adapter_flags,
    extract_adapter_names,
    load_json_strict,
    ordered_offsets,
    scan_forbidden_literals,
    scan_loader_calls,
    scan_prebuild_artifacts,
    validate_adapter_plan,
    validate_pe_import_inventory,
)


def test_strict_json_rejects_duplicate_keys() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "duplicate.json"
        path.write_text('{"schema": 1, "schema": 2}', encoding="utf-8")
        with pytest.raises(AuditFailure, match="duplicate JSON key"):
            load_json_strict(path)


def test_extract_adapter_names_and_derive_exact_flags() -> None:
    text = """
# Adapter drivers
m4_define([USB1_ADAPTERS],
    [[[alpha_one], [Alpha], [ALPHA]],
    [[beta], [Beta], [BETA]]])
m4_define([OPTIONAL_LIBRARIES], [])
"""
    assert extract_adapter_names(text) == ["alpha_one", "beta"]
    assert derive_adapter_flags(["beta"], ["alpha_one"]) == [
        "--enable-beta",
        "--disable-alpha-one",
    ]


def test_extract_adapter_names_rejects_duplicates() -> None:
    text = """
# Adapter drivers
m4_define([ONE], [[[alpha], [Alpha], [ALPHA]]])
m4_define([TWO], [[[alpha], [Alpha again], [ALPHA2]]])
m4_define([OPTIONAL_LIBRARIES], [])
"""
    with pytest.raises(AuditFailure, match="duplicates"):
        extract_adapter_names(text)


def test_adapter_plan_rejects_gap_and_overlap() -> None:
    with pytest.raises(AuditFailure, match="exact inventory"):
        validate_adapter_plan(["one", "two"], ["one"], [])
    with pytest.raises(AuditFailure, match="overlap"):
        validate_adapter_plan(["one"], ["one"], ["one"])


def test_ordered_offsets_rejects_absent_and_out_of_order_markers() -> None:
    assert ordered_offsets("alpha beta gamma", ["alpha", "beta", "gamma"], "fixture") == [0, 6, 11]
    with pytest.raises(AuditFailure, match="absent or out-of-order"):
        ordered_offsets("alpha beta gamma", ["beta", "alpha"], "fixture")


def test_loader_scan_finds_calls_but_not_declarations_or_comments() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "src"
        source.mkdir()
        (source / "runtime.c").write_text(
            "void *x = LoadLibraryA(\"x\");\nvoid *y = GetProcAddress(x, \"y\");\n",
            encoding="utf-8",
        )
        (source / "clean.h").write_text("typedef void *LoadLibraryA_t;\n", encoding="utf-8")
        assert scan_loader_calls(root, ["src"], [".c", ".h"]) == {
            "src/runtime.c": ["GetProcAddress", "LoadLibraryA"]
        }


def test_forbidden_literal_scan_is_case_insensitive() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "src"
        source.mkdir()
        (source / "runtime.c").write_text('const char *name = "UsbDkHelper.DLL";\n', encoding="utf-8")
        assert scan_forbidden_literals(root, ["src"], [".c"], ["usbdkhelper.dll"]) == {
            "src/runtime.c": ["usbdkhelper.dll"]
        }


def test_prebuild_artifact_scan_ignores_git_metadata_and_rejects_objects() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".git").mkdir()
        (root / ".git" / "internal.obj").write_bytes(b"git metadata")
        (root / "src").mkdir()
        (root / "src" / "compiled.OBJ").write_bytes(b"object")
        assert scan_prebuild_artifacts(root, [".obj", ".o"]) == ["src/compiled.OBJ"]


def _inventory(direct: list[str], delay: list[str] | None = None) -> dict[str, object]:
    return {
        "schema": 1,
        "image_sha256": "a" * 64,
        "direct_imports": direct,
        "delay_imports": [] if delay is None else delay,
    }


def _policy() -> dict[str, object]:
    return {
        "api_set_prefixes": ["api-ms-", "ext-ms-"],
        "adjacent_dlls_allowed": [],
        "delay_imports_allowed": [],
    }


def test_pe_policy_accepts_only_frozen_system_and_api_set_imports() -> None:
    validate_pe_import_inventory(
        _inventory(["api-ms-win-core-test-l1-1-0.dll", "kernel32.dll"]),
        _policy(),
        exact_system_dlls=["kernel32.dll"],
    )


@pytest.mark.parametrize(
    ("inventory", "message"),
    [
        (_inventory(["unexpected.dll"]), "not allowed"),
        (_inventory(["kernel32.dll"], ["delay.dll"]), "delay imports"),
        (_inventory(["KERNEL32.dll"]), "invalid DLL name"),
        (_inventory(["kernel32.dll", "kernel32.dll"]), "duplicates"),
        (_inventory(["z.dll", "a.dll"]), "sorted"),
    ],
)
def test_pe_policy_rejects_unfrozen_or_ambiguous_imports(
    inventory: dict[str, object], message: str
) -> None:
    with pytest.raises(AuditFailure, match=message):
        validate_pe_import_inventory(inventory, _policy(), exact_system_dlls=["kernel32.dll"])


def test_pe_policy_rejects_missing_frozen_system_allowlist() -> None:
    with pytest.raises(AuditFailure, match="not frozen"):
        validate_pe_import_inventory(_inventory(["kernel32.dll"]), _policy())


def test_phase0_manifest_is_fail_closed() -> None:
    manifest_path = Path(__file__).with_name("phase0_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "SOURCE_INVENTORY_ONLY_COMPILE_REFUSED"
    assert manifest["compile_authorized"] is False
    assert manifest["openocd_execution_authorized"] is False
    assert manifest["hardware_contact_authorized"] is False
    assert manifest["blockers"]
