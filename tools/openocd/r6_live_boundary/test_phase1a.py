from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tarfile

import pytest

from tools.openocd.r6_live_boundary.phase1a import (
    MANIFEST_PATH,
    Phase1AFailure,
    REPOSITORY,
    load_json_strict,
    sha256,
    validate_archive_projection,
    validate_manifest,
    verify_file,
)


def manifest() -> dict:
    return load_json_strict(MANIFEST_PATH)


def test_phase1a_manifest_is_desk_only_and_exact_child() -> None:
    value = manifest()
    validate_manifest(value)
    assert value["parent_agamemnon_commit"] == "2fee9bce38980f42bfb08ab479f89199cdf0ede3"
    assert value["compile_authorized"] is False
    assert value["openocd_execution_authorized"] is False
    assert value["hardware_contact_authorized"] is False
    assert value["required_future_gates"]


def test_toolchain_decision_resolves_observed_drift_without_rolling_ci() -> None:
    value = manifest()
    release = load_json_strict(REPOSITORY / "tools/openocd/manifest.json")
    observation = load_json_strict(MANIFEST_PATH.with_name("tool_observation.json"))
    assert observation["blocking_mismatches"] == []
    for label in ("compiler", "pkgconf"):
        record = value["toolchain_decision"][label]
        package = record["package"]
        assert release["build_environment"]["windows"]["packages"][package] == record["version"]
        assert observation["package_versions"][package] == {
            "expected": record["version"],
            "observed": record["version"],
            "status": "MATCH",
        }
        assert observation["file_identities"][record["executable_path"]] == {
            "size": record["executable_size"],
            "sha256": record["executable_sha256"],
        }
    assert value["toolchain_decision"]["rolling_ci_package_resolution_allowed"] is False


def test_all_phase1a_patches_are_hash_bound() -> None:
    value = manifest()
    for record in (value["openocd_source"], value["jimtcl"], value["libusb"]):
        path = REPOSITORY / record["patch"]
        assert path.is_file()
        assert sha256(path) == record["patch_sha256"]


def test_earliest_main_patch_is_unconditional_and_ordered() -> None:
    value = manifest()
    patch = (REPOSITORY / value["openocd_source"]["patch"]).read_text(encoding="utf-8")
    gate = value["earliest_main_gate"]
    positions = [patch.index(token) for token in gate["required_order"]]
    assert positions == sorted(positions)
    assert "return R6_LIVE_BOUNDARY_DENIED;" in patch
    assert gate["mode"] == "DENY_ONLY"
    assert gate["allowed_calls"] == []
    assert gate["authorization_inputs"] == []
    assert gate["denied_exit_code"] == 70


def test_jimtcl_patch_removes_runtime_loader_from_selected_configuration() -> None:
    value = manifest()
    openocd_patch = (REPOSITORY / value["openocd_source"]["patch"]).read_text(
        encoding="utf-8"
    )
    jim_patch = (REPOSITORY / value["jimtcl"]["patch"]).read_text(encoding="utf-8")
    assert "--without-ext=load" in openocd_patch
    assert "defined(HAVE_DLOPEN_COMPAT) && defined(jim_ext_load)" in jim_patch
    assert value["jimtcl"]["required_absent_final_objects"] == ["jim-load.o"]
    assert value["jimtcl"]["conditional_object_forbidden_imports"] == [
        "LoadLibraryA", "GetProcAddress"
    ]
    assert value["jimtcl"]["final_membership_proof_complete"] is False


def test_libusb_patch_is_winusb_only_and_refuses_installed_library() -> None:
    value = manifest()
    record = value["libusb"]
    patch = (REPOSITORY / record["patch"]).read_text(encoding="utf-8")
    for marker in (
        "-\t\t os/windows_usbdk.h os/windows_usbdk.c",
        "+static const char * const winusbx_driver_names[] = {NULL, NULL, \"WinUSB\"};",
        "+\t\tif (sub_api != SUB_API_WINUSB)",
        "-\thlibusbK = load_system_library(ctx, \"libusbK\");",
        "+\tif (hWinUSB == NULL)",
    ):
        assert marker in patch
    assert "load_system_library(ctx, \"WinUSB\")" in patch
    assert record["selected_backend"] == "MICROSOFT_WINUSB_SYSTEM32_ONLY"
    assert record["system_or_preinstalled_libusb_link_allowed"] is False
    assert record["final_membership_proof_complete"] is False


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("compile_authorized", True, "compile_authorized"),
        ("openocd_execution_authorized", True, "openocd_execution_authorized"),
        ("hardware_contact_authorized", True, "hardware_contact_authorized"),
    ],
)
def test_manifest_rejects_authority_expansion(field: str, replacement: bool, message: str) -> None:
    value = manifest()
    value[field] = replacement
    with pytest.raises(Phase1AFailure, match=message):
        validate_manifest(value)


def test_manifest_rejects_unknown_key_and_desk_override() -> None:
    value = manifest()
    value["unexpected"] = False
    with pytest.raises(Phase1AFailure, match="keys differ"):
        validate_manifest(value)

    value = manifest()
    value["earliest_main_gate"]["desk_override_allowed"] = True
    with pytest.raises(Phase1AFailure, match="desk override"):
        validate_manifest(value)


def test_manifest_rejects_backend_or_final_proof_preclaim() -> None:
    value = manifest()
    value["libusb"]["selected_backend"] = "AUTO"
    with pytest.raises(Phase1AFailure, match="WinUSB-only"):
        validate_manifest(value)

    value = manifest()
    value["jimtcl"]["final_membership_proof_complete"] = True
    with pytest.raises(Phase1AFailure, match="cannot be preclaimed"):
        validate_manifest(value)


def test_strict_json_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema": 1, "schema": 1}\n', encoding="utf-8")
    with pytest.raises(Phase1AFailure, match="duplicate JSON key"):
        load_json_strict(path)


def test_file_identity_rejects_size_and_hash_mutation(tmp_path: Path) -> None:
    path = tmp_path / "input.bin"
    path.write_bytes(b"frozen")
    digest = sha256(path)
    verify_file(path, 6, digest, "fixture")
    path.write_bytes(b"changed")
    with pytest.raises(Phase1AFailure, match="size differs"):
        verify_file(path, 6, digest, "fixture")
    path.write_bytes(b"mutate")
    with pytest.raises(Phase1AFailure, match="SHA-256 differs"):
        verify_file(path, 6, digest, "fixture")


def _write_tar(path: Path, member_name: str = "source/file.txt") -> None:
    payload = b"frozen\n"
    with tarfile.open(path, "w:bz2") as bundle:
        root = tarfile.TarInfo("source")
        root.type = tarfile.DIRTYPE
        bundle.addfile(root)
        member = tarfile.TarInfo(member_name)
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))


def test_archive_projection_rejects_extra_and_mutated_members(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.bz2"
    _write_tar(archive)
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_bytes(b"frozen\n")
    validate_archive_projection(archive, source, "source")

    (source / "extra.txt").write_bytes(b"extra")
    with pytest.raises(Phase1AFailure, match="inventory differs"):
        validate_archive_projection(archive, source, "source")
    (source / "extra.txt").unlink()
    (source / "file.txt").write_bytes(b"changed")
    with pytest.raises(Phase1AFailure, match="SHA-256 differs"):
        validate_archive_projection(archive, source, "source")


def test_archive_projection_rejects_escape_member(tmp_path: Path) -> None:
    archive = tmp_path / "escape.tar.bz2"
    _write_tar(archive, "source/../escape.txt")
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(Phase1AFailure, match="escapes"):
        validate_archive_projection(archive, source, "source")


def test_manifest_patch_hash_mutation_is_observable(tmp_path: Path) -> None:
    value = copy.deepcopy(manifest())
    source = REPOSITORY / value["openocd_source"]["patch"]
    target = tmp_path / source.name
    target.write_bytes(source.read_bytes() + b"\n")
    assert sha256(target) != value["openocd_source"]["patch_sha256"]


def test_manifest_is_canonical_json_shape() -> None:
    raw = MANIFEST_PATH.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw) == manifest()
