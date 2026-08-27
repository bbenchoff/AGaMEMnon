from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tools.openocd.r6_live_boundary.audit import (
    AuditFailure,
    derive_adapter_flags,
    discover_build_rule_directories,
    discover_directory_creation_occurrences,
    dynamic_reference_counts,
    extract_adapter_names,
    load_json_strict,
    ignored_untracked_directories,
    ignored_untracked_files,
    ordered_offsets,
    scan_build_artifacts,
    scan_dynamic_references,
    scan_forbidden_literals,
    scan_loader_calls,
    sha256_file,
    validate_adapter_plan,
    validate_artifact_rule_inventory,
    validate_build_rule_directory_inventory,
    validate_directory_creation_occurrences,
    validate_dynamic_reference_inventory,
    validate_loader_inventory,
    validate_pe_import_inventory,
    validate_tool_observation,
    validate_tracked_fixture_inventory,
    verify_file_binding,
)


def _init_git_repository(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["git", "-C", str(path), "init", "--quiet"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    assert completed.returncode == 0, completed.stderr


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
            "void *dlopen(const char *path, int mode);\n"
            "void *dlsym(void *handle, const char *name);\n"
            "void *\nLoadLibraryW(const char *path);\n"
            "static void (*sqlite3OsDlSym(void *vfs, void *h, const char *name))(void);\n"
            "static int Win32_LoadLibrary(void *interp) { return 0; }\n"
            "/* Jim_LoadLibrary(interp, path); */\n"
            "const char *not_code = \"xDlSym(vfs, path);\";\n"
            "void *x = LoadLibraryA(\"x\");\n"
            "void *y = dlopen(\"y\", 0);\n"
            "void *symbol = dlsym(y, \"entry\");\n"
            "int z = Jim_LoadLibrary(interp, path);\n"
            "void *w = osLoadLibraryW(path);\n"
            "void *a = osGetProcAddressA(w, \"entry\");\n"
            "void *b = sqlite3OsDlSym(vfs, w, \"entry\");\n"
            "void *c = vfs->xDlSym(vfs, w, \"entry\");\n",
            encoding="utf-8",
        )
        (source / "clean.h").write_text("typedef void *LoadLibraryA_t;\n", encoding="utf-8")
        assert scan_loader_calls(root, ["src"], [".c", ".h"]) == {
            "src/runtime.c": {
                "Jim_LoadLibrary": 1,
                "LoadLibraryA": 1,
                "dlopen": 1,
                "dlsym": 1,
                "osGetProcAddressA": 1,
                "osLoadLibraryW": 1,
                "sqlite3OsDlSym": 1,
                "xDlSym": 1,
            }
        }


def test_dynamic_reference_scan_freezes_declarations_and_prefixed_wrappers() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "src"
        source.mkdir()
        runtime = source / "runtime.c"
        runtime.write_text(
            "void *dlsym(void *handle, const char *name);\n"
            "static void (*sqlite3OsDlSym(void *vfs, void *h, const char *name))(void);\n"
            "/* hidden_dlsym(handle, name); */\n"
            "const char *not_code = \"string_dlopen(path)\";\n"
            "void *a = lt_dlsym(handle, name);\n"
            "void *b = Jim_dlopen(path, 0);\n",
            encoding="utf-8",
        )
        expected = {
            "src/runtime.c": {
                "Jim_dlopen": 1,
                "dlsym": 1,
                "lt_dlsym": 1,
                "sqlite3OsDlSym": 1,
            }
        }
        actual = scan_dynamic_references(root, ["src"], [".c"])
        assert actual == expected
        validate_dynamic_reference_inventory(actual, expected)

        runtime.write_text(
            runtime.read_text(encoding="utf-8")
            + "void *c = newly_prefixed_dlsym(handle, name);\n",
            encoding="utf-8",
        )
        with pytest.raises(AuditFailure, match="dynamic reference/path inventory"):
            validate_dynamic_reference_inventory(
                scan_dynamic_references(root, ["src"], [".c"]), expected
            )


def test_dynamic_reference_counter_blanks_comments_strings_and_characters() -> None:
    assert dynamic_reference_counts(
        "/* fake_dlsym(x); */\n"
        'const char *s = "fake_dlopen(y)";\n'
        "int c = 'd';\n"
        "void *x = real_dlsym(handle, name);\n"
    ) == {"real_dlsym": 1}


def test_loader_inventory_rejects_direct_and_indirect_mutations() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "src"
        source.mkdir()
        runtime = source / "runtime.c"
        runtime.write_text("void *x = LoadLibraryA(path);\n", encoding="utf-8")
        expected = {"src/runtime.c": {"LoadLibraryA": 1}}
        validate_loader_inventory(scan_loader_calls(root, ["src"], [".c"]), expected)

        runtime.write_text(
            "void *x = LoadLibraryA(path);\nvoid *y = dlopen(path, 0);\n",
            encoding="utf-8",
        )
        with pytest.raises(AuditFailure, match="call/path inventory"):
            validate_loader_inventory(scan_loader_calls(root, ["src"], [".c"]), expected)

        runtime.write_text("void *x = LoadLibraryA(path);\n", encoding="utf-8")
        (source / "indirect.c").write_text(
            "int result = Jim_LoadLibrary(interp, path);\n", encoding="utf-8"
        )
        with pytest.raises(AuditFailure, match="call/path inventory"):
            validate_loader_inventory(scan_loader_calls(root, ["src"], [".c"]), expected)


def test_forbidden_literal_scan_is_case_insensitive() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "src"
        source.mkdir()
        (source / "runtime.c").write_text('const char *name = "UsbDkHelper.DLL";\n', encoding="utf-8")
        assert scan_forbidden_literals(root, ["src"], [".c"], ["usbdkhelper.dll"]) == {
            "src/runtime.c": ["usbdkhelper.dll"]
        }


def test_artifact_scan_catches_ignored_libraries_and_build_directories() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".git").mkdir()
        (root / ".git" / "internal.a").write_bytes(b"git metadata")
        (root / ".gitignore").write_text("*.a\n.libs/\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "tracked-fixture.elf").write_bytes(b"frozen fixture")
        (root / "src" / "ignored.a").write_bytes(b"archive")
        (root / "src" / "runtime.LIB").write_bytes(b"library")
        (root / "src" / "versioned.so.1").write_bytes(b"shared library")
        (root / ".libs").mkdir()
        (root / "cmake-build-release").mkdir()
        assert scan_build_artifacts(
            root,
            [".a", ".elf", ".lib", ".so"],
            [r"(?i)\.so(?:\.[0-9]+)+$"],
            [".libs"],
            ["cmake-build-"],
            ["src/tracked-fixture.elf"],
        ) == {
            "files": ["src/ignored.a", "src/runtime.LIB", "src/versioned.so.1"],
            "directories": [".libs", "cmake-build-release"],
        }


def test_artifact_scan_adversarially_catches_every_derived_exact_product_and_directory() -> None:
    inventory = load_json_strict(Path(__file__).with_name("artifact_rule_inventory.json"))
    manifest = load_json_strict(Path(__file__).with_name("phase0_manifest.json"))
    policy = manifest["source_inventory"]["artifact_policy"]
    exact_products = sorted(inventory["exact_product_paths"])
    derived_directories = sorted(inventory["derived_directory_names"])
    assert exact_products == sorted(policy["exact_file_paths"])
    assert set(derived_directories).issubset(policy["directory_names"])

    for exact_product in exact_products:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / exact_product
            product.parent.mkdir(parents=True, exist_ok=True)
            product.write_bytes(b"adversarial ignored product")
            assert scan_build_artifacts(
                root, [], [], [], [], exact_file_paths=exact_products
            )["files"] == [exact_product]

    for directory_name in derived_directories:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product_directory = root / "nested" / directory_name
            product_directory.mkdir(parents=True)
            assert scan_build_artifacts(
                root, [], [], derived_directories, []
            )["directories"] == [f"nested/{directory_name}"]


def test_git_ignored_gate_detects_extensionless_file_and_empty_product_directory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _init_git_repository(root)
        (root / ".gitignore").write_text(
            "ignored-extensionless\nbuild-jim-ext/\n", encoding="utf-8"
        )
        (root / "ignored-extensionless").write_bytes(b"product")
        (root / "build-jim-ext").mkdir()
        assert ignored_untracked_files(root) == ["ignored-extensionless"]
        assert ignored_untracked_directories(root) == ["build-jim-ext/"]


def test_active_build_rules_catch_nonignored_empty_dep_independently_of_inventory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _init_git_repository(root)
        (root / ".gitignore").write_text("unrelated-product\n", encoding="utf-8")
        example = root / "testing/examples/example"
        example.mkdir(parents=True)
        (example / "makefile").write_text(
            "-include $(shell mkdir .dep 2>/dev/null) $(wildcard .dep/*)\n",
            encoding="utf-8",
        )
        (example / ".dep").mkdir()

        discovered = discover_build_rule_directories(root)
        assert discovered == {".dep": ["testing/examples/example/makefile"]}
        assert ignored_untracked_directories(root) == []
        assert scan_build_artifacts(
            root, [], [], list(discovered), []
        )["directories"] == ["testing/examples/example/.dep"]

        with pytest.raises(AuditFailure, match="build-rule directory inventory differs"):
            validate_build_rule_directory_inventory(discovered, {}, {}, {})

        occurrence_policy = [
            {
                "source": "testing/examples/example/makefile",
                "line": 1,
                "expression": "-include $(shell mkdir .dep 2>/dev/null) $(wildcard .dep/*)",
                "kind": "LITERAL_MKDIR",
                "disposition": "FORBIDDEN_DIRECTORY_NAME",
                "resolved_directory_names": [".dep"],
            }
        ]
        occurrences = discover_directory_creation_occurrences(root)
        validate_directory_creation_occurrences(
            occurrences,
            occurrence_policy,
            [".dep"],
            [],
            {"testing/examples/example/makefile": "bound"},
        )
        with pytest.raises(AuditFailure, match="occurrence inventory differs"):
            validate_directory_creation_occurrences(
                [],
                occurrence_policy,
                [".dep"],
                [],
                {"testing/examples/example/makefile": "bound"},
            )
        (example / "makefile").write_text(
            (example / "makefile").read_text(encoding="utf-8")
            + "MKDIR := mkdir -p\n$(MKDIR) $(OUTPUT_DIR)\n",
            encoding="utf-8",
        )
        with pytest.raises(AuditFailure, match="occurrence inventory differs"):
            validate_directory_creation_occurrences(
                discover_directory_creation_occurrences(root),
                occurrence_policy,
                [".dep"],
                [],
                {"testing/examples/example/makefile": "bound"},
            )


def test_exact_two_ignored_patch_exceptions_pass_and_all_drift_rejects() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _init_git_repository(root)
        _init_git_repository(root / "jimtcl")
        _init_git_repository(root / "src/jtag/drivers/libjaylink")
        patch_directory = root / "AGAMEMNON-PATCHES"
        patch_directory.mkdir()
        patch_names = [
            "0001-target-riscv-DM-access-on-a-DAP.patch",
            "0002-target-riscv-fix-nested-ADIv5-config.patch",
        ]
        (root / ".gitignore").write_text(
            "\n".join(f"AGAMEMNON-PATCHES/{name}" for name in patch_names) + "\n",
            encoding="utf-8",
        )
        for index, name in enumerate(patch_names, start=1):
            (patch_directory / name).write_bytes(f"patch-{index}".encode("ascii"))

        expected_files = {
            f"AGAMEMNON-PATCHES/{name}": sha256_file(patch_directory / name)
            for name in patch_names
        }
        rule_inventory = {
            "schema": 1,
            "kind": "R6_OPENOCD_DERIVED_ARTIFACT_RULE_INVENTORY",
            "source_tree": "a" * 40,
            "rule_sources": {},
            "exact_product_paths": {},
            "derived_directory_names": {},
            "build_rule_directory_sources": {},
            "directory_creation_occurrences": [],
            "ignored_untracked_expected": {
                ".": expected_files,
                "jimtcl": {},
                "src/jtag/drivers/libjaylink": {},
            },
        }
        policy = {
            "exact_file_paths": [],
            "directory_names": [],
            "directory_prefixes": [],
        }
        validate_artifact_rule_inventory(root, policy, rule_inventory, "a" * 40)

        first_patch = patch_directory / patch_names[0]
        first_original = first_patch.read_bytes()
        first_patch.write_bytes(b"mutated patch")
        with pytest.raises(AuditFailure, match="metadata hash differs"):
            validate_artifact_rule_inventory(root, policy, rule_inventory, "a" * 40)
        first_patch.write_bytes(first_original)

        first_patch.unlink()
        with pytest.raises(AuditFailure, match="ignored untracked files differ"):
            validate_artifact_rule_inventory(root, policy, rule_inventory, "a" * 40)
        first_patch.write_bytes(first_original)

        third_name = "0003-unreviewed.patch"
        with (root / ".gitignore").open("a", encoding="utf-8") as stream:
            stream.write(f"AGAMEMNON-PATCHES/{third_name}\n")
        (patch_directory / third_name).write_bytes(b"unreviewed patch")
        with pytest.raises(AuditFailure, match="ignored untracked files differ"):
            validate_artifact_rule_inventory(root, policy, rule_inventory, "a" * 40)


def test_tracked_fixture_inventory_rejects_mutate_remove_and_add_bypasses() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fixture = root / "fixture.elf"
        fixture.write_bytes(b"frozen fixture")
        tracked_files = ["fixture.elf"]
        policy = {
            "file_suffixes": [".elf"],
            "file_name_regexes": [],
            "tracked_fixture_artifacts": ["fixture.elf"],
        }
        fixture_manifest = {
            "schema": 1,
            "kind": "R6_OPENOCD_TRACKED_FIXTURE_ARTIFACTS",
            "source_tree": "a" * 40,
            "artifacts": {"fixture.elf": sha256_file(fixture)},
        }
        assert validate_tracked_fixture_inventory(
            root, tracked_files, policy, fixture_manifest, "a" * 40
        ) == ["fixture.elf"]

        fixture.write_bytes(b"broken fixture")
        with pytest.raises(AuditFailure, match="fixture SHA-256 differs"):
            validate_tracked_fixture_inventory(
                root, tracked_files, policy, fixture_manifest, "a" * 40
            )
        fixture.write_bytes(b"frozen fixture")

        removed_record = json.loads(json.dumps(fixture_manifest))
        del removed_record["artifacts"]["fixture.elf"]
        with pytest.raises(AuditFailure, match="fixture hash records"):
            validate_tracked_fixture_inventory(
                root, tracked_files, policy, removed_record, "a" * 40
            )

        added_record = json.loads(json.dumps(fixture_manifest))
        added_record["artifacts"]["untracked.elf"] = "b" * 64
        with pytest.raises(AuditFailure, match="fixture hash records"):
            validate_tracked_fixture_inventory(
                root, tracked_files, policy, added_record, "a" * 40
            )

        fixture.unlink()
        with pytest.raises(AuditFailure, match="tracked fixture absent"):
            validate_tracked_fixture_inventory(
                root, tracked_files, policy, fixture_manifest, "a" * 40
            )


def test_bound_file_rejects_any_observation_mutation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "observation.json"
        path.write_text('{"build_allowed": false}\n', encoding="utf-8")
        frozen_hash = sha256_file(path)
        verify_file_binding(path, frozen_hash, "observation")
        path.write_text('{"build_allowed": true}\n', encoding="utf-8")
        with pytest.raises(AuditFailure, match="hash differs"):
            verify_file_binding(path, frozen_hash, "observation")


def _tool_observation_fixture(identity_path: Path) -> tuple[dict, dict, dict]:
    raw_path = identity_path.as_posix()
    release_manifest = {
        "build_environment": {
            "windows": {
                "reference_packages": ["reference"],
                "packages": {"compiler": "2", "reference": "1"},
            }
        }
    }
    policy = {
        "platform": "windows",
        "expected_blocking_mismatches": ["compiler"],
        "required_identity_paths": [raw_path],
    }
    observation = {
        "schema": 1,
        "kind": "R6_LIVE_BOUNDARY_READ_ONLY_TOOL_OBSERVATION",
        "source_prepared_only": True,
        "build_attempted": False,
        "openocd_executed": False,
        "build_allowed": False,
        "package_versions": {
            "compiler": {
                "expected": "2",
                "observed": "1",
                "status": "MISMATCH_BUILD_BLOCKED",
            },
            "reference": {
                "expected": "1",
                "observed": "1",
                "status": "REFERENCE_MATCH",
            },
        },
        "file_identities": {
            raw_path: {"size": identity_path.stat().st_size, "sha256": sha256_file(identity_path)}
        },
        "blocking_mismatches": ["compiler"],
    }
    return observation, release_manifest, policy


def test_tool_observation_rejects_package_mismatch_and_identity_bypasses() -> None:
    with tempfile.TemporaryDirectory() as directory:
        identity_path = Path(directory).resolve() / "tool.exe"
        identity_path.write_bytes(b"frozen tool")
        observation, release_manifest, policy = _tool_observation_fixture(identity_path)
        validate_tool_observation(observation, release_manifest, policy)

        missing_package = json.loads(json.dumps(observation))
        del missing_package["package_versions"]["reference"]
        with pytest.raises(AuditFailure, match="package records"):
            validate_tool_observation(missing_package, release_manifest, policy)

        hidden_mismatch = json.loads(json.dumps(observation))
        hidden_mismatch["package_versions"]["compiler"] = {
            "expected": "2",
            "observed": "2",
            "status": "MATCH",
        }
        hidden_mismatch["blocking_mismatches"] = []
        with pytest.raises(AuditFailure, match="derived package mismatch set"):
            validate_tool_observation(hidden_mismatch, release_manifest, policy)

        wrong_size = json.loads(json.dumps(observation))
        raw_path = identity_path.as_posix()
        wrong_size["file_identities"][raw_path]["size"] += 1
        with pytest.raises(AuditFailure, match="size differs"):
            validate_tool_observation(wrong_size, release_manifest, policy)

        removed_identity = json.loads(json.dumps(observation))
        del removed_identity["file_identities"][raw_path]
        with pytest.raises(AuditFailure, match="file identities"):
            validate_tool_observation(removed_identity, release_manifest, policy)

        added_identity = json.loads(json.dumps(observation))
        added_identity["file_identities"][raw_path + ".extra"] = {
            "size": 1,
            "sha256": "c" * 64,
        }
        with pytest.raises(AuditFailure, match="file identities"):
            validate_tool_observation(added_identity, release_manifest, policy)

        identity_path.write_bytes(b"broken tool")
        with pytest.raises(AuditFailure, match="SHA-256 differs"):
            validate_tool_observation(observation, release_manifest, policy)


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
    assert manifest["tool_observation_policy"]["expected_blocking_mismatches"] == [
        "mingw-w64-ucrt-x86_64-gcc",
        "mingw-w64-ucrt-x86_64-pkgconf",
    ]
    assert "tools/openocd/r6_live_boundary/tool_observation.json" in manifest[
        "deterministic_inputs"
    ]
    assert len(manifest["source_inventory"]["artifact_policy"]["tracked_fixture_artifacts"]) == 49
    repository = Path(__file__).resolve().parents[3]
    for relative in (
        manifest["tool_observation_policy"]["schema_path"],
        manifest["pe_import_policy"]["schema_path"],
        manifest["source_inventory"]["artifact_policy"]["fixture_manifest_path"],
    ):
        assert manifest["deterministic_inputs"][relative] == sha256_file(repository / relative)


def test_bound_policy_schemas_are_strict_json() -> None:
    directory = Path(__file__).parent
    for name in ("pe_import_policy.schema.json", "tool_observation.schema.json"):
        schema = load_json_strict(directory / name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
