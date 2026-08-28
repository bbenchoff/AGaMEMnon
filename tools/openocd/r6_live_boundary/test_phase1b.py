from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.openocd.r6_live_boundary import phase1b


def manifest() -> dict:
    return phase1b.load_json_strict(phase1b.MANIFEST_PATH)


def test_manifest_is_exact_compile_only_child() -> None:
    value = manifest()
    phase1b.validate_manifest(value)
    assert value["parent_agamemnon_commit"] == phase1b.ACCEPTED_PHASE1A
    assert value["compile_authorized"] is True
    assert value["openocd_execution_authorized"] is False
    assert value["hardware_contact_authorized"] is False


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("compile_authorized", False, "compilation"),
        ("openocd_execution_authorized", True, "execution"),
        ("hardware_contact_authorized", True, "hardware"),
    ],
)
def test_manifest_rejects_authority_drift(field: str, replacement, message: str) -> None:
    value = manifest()
    value[field] = replacement
    with pytest.raises(phase1b.Phase1BFailure, match=message):
        phase1b.validate_manifest(value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["build_contract"].__setitem__("configure_flags", []),
        lambda value: value["build_contract"].__setitem__(
            "enabled_adapter_macros", ["BUILD_CMSIS_DAP_HID"]
        ),
        lambda value: value["build_contract"].__setitem__("forbidden_objects", []),
        lambda value: value["artifact_evidence"].__setitem__("direct_imports", []),
        lambda value: value["artifact_evidence"].__setitem__("main_instructions", []),
        lambda value: value.__setitem__("remaining_gates", ["PLACEHOLDER"]),
    ],
)
def test_manifest_rejects_semantic_policy_weakening(mutate) -> None:
    value = manifest()
    mutate(value)
    with pytest.raises(phase1b.Phase1BFailure):
        phase1b.validate_manifest(value)


def test_manifest_rejects_unknown_key_and_duplicate_json(tmp_path: Path) -> None:
    value = manifest()
    value["unexpected"] = False
    with pytest.raises(phase1b.Phase1BFailure, match="keys differ"):
        phase1b.validate_manifest(value)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema": 1, "schema": 1}\n', encoding="utf-8")
    with pytest.raises(phase1b.Phase1BFailure, match="duplicate JSON key"):
        phase1b.load_json_strict(duplicate)


def test_prepared_source_contract_binds_all_three_patches() -> None:
    value = manifest()
    prior = phase1b.phase1a.load_json_strict(phase1b.PHASE1A_MANIFEST_PATH)
    assert value["prepared_source"]["openocd"]["inventory"]["file_count"] == 2640
    assert value["prepared_source"]["libusb"]["inventory"]["file_count"] == 151
    assert len(value["prepared_source"]["postpatch_files"]) == 6
    for record in (prior["openocd_source"], prior["jimtcl"], prior["libusb"]):
        patch = phase1b.REPOSITORY / record["patch"]
        assert phase1b.sha256(patch) == record["patch_sha256"]


def test_build_script_has_no_openocd_execution_and_uses_fixed_destdir() -> None:
    script = phase1b.MANIFEST_PATH.with_name("phase1b_build.sh").read_text(encoding="utf-8")
    assert "PASS_PHASE1B_BUILD_COMPLETE_OPENOCD_NOT_EXECUTED" in script
    assert "openocd.exe --version" not in script
    assert '"$openocd_prefix/bin/openocd.exe"' not in script
    assert "openocd_install_prefix=/opt/agamemnon-openocd" in script
    assert "libusb_install_prefix=/opt/agamemnon-libusb" in script
    assert 'make install DESTDIR="$openocd_stage"' in script
    assert 'make install DESTDIR="$libusb_stage"' in script
    assert "verify-prepared" in script
    assert "PKG_CONFIG_LIBDIR=\"$libusb_prefix/lib/pkgconfig\"" in script


def test_artifact_contract_is_winusb_only_and_deny_only() -> None:
    value = manifest()
    evidence = value["artifact_evidence"]
    members = evidence["libusb_archive"]["members"]
    assert members == [
        "core.o", "descriptor.o", "hotplug.o", "io.o", "strerror.o", "sync.o",
        "events_windows.o", "threads_windows.o", "libusb-1.0.o",
        "windows_common.o", "windows_winusb.o",
    ]
    assert "windows_usbdk.o" not in members
    assert evidence["delay_imports"] == []
    assert evidence["adjacent_bin_files"] == ["openocd.exe"]
    instructions = evidence["main_instructions"]
    assert instructions[:5] == [
        "sub    $0x28,%rsp",
        "call   <__main>",
        "mov    $0x46,%eax",
        "add    $0x28,%rsp",
        "ret",
    ]
    assert not any("openocd_main" in item or "setvbuf" in item for item in instructions)


def test_static_import_allowlist_is_exact() -> None:
    imports = manifest()["artifact_evidence"]["direct_imports"]
    assert imports == sorted(imports)
    assert imports[0].startswith("api-ms-win-crt-")
    assert imports[-1] == "kernel32.dll"
    assert all(item.startswith("api-ms-") or item == "kernel32.dll" for item in imports)


def test_normalize_build_paths_covers_windows_posix_and_msys_forms() -> None:
    root = Path("C:/Users/ExampleUser/build-root")
    text = (
        "C:\\Users\\ExampleUser\\build-root/x "
        "C:/Users/ExampleUser/build-root/y "
        "/c/Users/ExampleUser/build-root/z"
    )
    normalized = phase1b.normalize_build_paths(text, root)
    assert "ExampleUser" not in normalized
    assert normalized.count("@BUILD_ROOT@") == 3


def test_inventory_detects_content_and_path_changes(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "one.txt").write_bytes(b"one")
    first = phase1b.inventory(root)
    (root / "one.txt").write_bytes(b"two")
    second = phase1b.inventory(root)
    assert first["file_count"] == second["file_count"] == 1
    assert first["records_sha256"] != second["records_sha256"]
    (root / "two.txt").write_bytes(b"two")
    assert phase1b.inventory(root)["file_count"] == 2


def test_object_inventory_detects_object_mutation(tmp_path: Path) -> None:
    (tmp_path / "a.o").write_bytes(b"a")
    first = phase1b.object_inventory(tmp_path)
    (tmp_path / "a.o").write_bytes(b"b")
    second = phase1b.object_inventory(tmp_path)
    assert first["count"] == second["count"] == 1
    assert first["records_sha256"] != second["records_sha256"]


def test_configure_and_link_records_must_be_unique(tmp_path: Path) -> None:
    build = tmp_path
    (build / "openocd-build").mkdir()
    (build / "openocd-build/config.log").write_text(
        f"  $ {build.as_posix()}/openocd-source/configure --prefix=/opt/agamemnon-openocd\n",
        encoding="utf-8",
    )
    assert phase1b._configure_invocation(build).startswith("@BUILD_ROOT@/openocd-source")
    (build / "openocd-build.log").write_text(
        "libtool: link: x86_64-w64-mingw32-gcc -o src/openocd.exe input.a\n",
        encoding="utf-8",
    )
    assert "-o src/openocd.exe" in phase1b._link_invocation(build)
    with (build / "openocd-build.log").open("a", encoding="utf-8") as stream:
        stream.write("libtool: link: x86_64-w64-mingw32-gcc -o src/openocd.exe other.a\n")
    with pytest.raises(phase1b.Phase1BFailure, match="not unique"):
        phase1b._link_invocation(build)


def test_pe_import_parser_rejects_nonzero_delay_directory(monkeypatch) -> None:
    value = manifest()
    good = """
Entry 1 00001000 00000010 Import Directory
 DLL Name: KERNEL32.dll
Entry d 00000000 00000000 Delay Import Directory
"""
    monkeypatch.setattr(phase1b, "_tool", lambda *_args: good)
    direct, delay = phase1b._pe_imports(value, Path("unused.exe"))
    assert direct == ["kernel32.dll"]
    assert delay == []
    bad = good.replace("Entry d 00000000 00000000", "Entry d 00001000 00000010")
    monkeypatch.setattr(phase1b, "_tool", lambda *_args: bad)
    assert phase1b._pe_imports(value, Path("unused.exe"))[1] == ["present"]


def test_main_disassembly_parser_normalizes_compiler_runtime_call(monkeypatch) -> None:
    output = """0000000140001000 <main>:
  140001000: 48 83 ec 28  sub    $0x28,%rsp
  140001004: e8 00 00 00 00  call   140001009 <__main>
  140001009: b8 46 00 00 00  mov    $0x46,%eax
  14000100e: c3  ret

0000000140001010 <next>:
"""
    monkeypatch.setattr(phase1b, "_tool", lambda *_args: output)
    assert phase1b._main_instructions(manifest(), Path("unused.exe")) == [
        "sub    $0x28,%rsp", "call   <__main>", "mov    $0x46,%eax", "ret"
    ]


def test_candidate_rejects_merge_path_drift_and_dirty_tree(monkeypatch) -> None:
    parent = phase1b.ACCEPTED_PHASE1A
    monkeypatch.setattr(phase1b, "git", lambda _repo, *_args: f"head {parent} extra")
    with pytest.raises(phase1b.Phase1BFailure, match="one parent"):
        phase1b.validate_candidate(Path("unused"), parent)

    def wrong_paths(_repo: Path, *args: str) -> str:
        if args[0] == "rev-list":
            return f"head {parent}"
        if args[0] == "diff":
            return "unexpected"
        return ""

    monkeypatch.setattr(phase1b, "git", wrong_paths)
    with pytest.raises(phase1b.Phase1BFailure, match="path inventory"):
        phase1b.validate_candidate(Path("unused"), parent)


def test_manifest_is_canonical_and_semantically_bound() -> None:
    raw = phase1b.MANIFEST_PATH.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    value = json.loads(raw)
    digest = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    assert digest == phase1b.EXPECTED_MANIFEST_SEMANTIC_SHA256
