from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest

from tools.openocd import release as openocd_release
from tools.openocd.r6_live_boundary.audit import (
    AuditFailure,
    EXPECTED_GENERATED_SOURCE_PATHS,
    canonical_provenance_bytes,
    derive_adapter_flags,
    derive_source_provenance,
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
    validate_generated_source_topology,
    validate_loader_inventory,
    validate_pe_import_inventory,
    validate_repository_source_state,
    validate_source_provenance_file,
    validate_tool_observation,
    validate_tracked_fixture_inventory,
    validate_zero_extra_directories,
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


def _git_add(repository: Path, *paths: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repository), "add", "--", *paths],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    assert completed.returncode == 0, completed.stderr


def _git_commit_fixture(repository: Path) -> None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Phase0 Test",
            "-c",
            "user.email=phase0@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    assert completed.returncode == 0, completed.stderr


def _git_fixture_command(
    repository: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        input=input_bytes,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed


def _source_state_fixture(tmp_path: Path) -> tuple[Path, bytes]:
    repository = tmp_path / "source-state"
    _init_git_repository(repository)
    original = b"frozen tracked bytes\n"
    (repository / "tracked.txt").write_bytes(original)
    (repository / ".gitignore").write_text("ignored-generated.txt\n", encoding="utf-8")
    _git_add(repository, "tracked.txt", ".gitignore")
    _git_commit_fixture(repository)
    return repository, original


def _nested_source_state_fixture(tmp_path: Path) -> tuple[Path, bytes]:
    repository = tmp_path / "nested-source-state"
    _init_git_repository(repository)
    original = b"nested frozen tracked bytes\n"
    nested = repository / "nested"
    nested.mkdir()
    (nested / "tracked.txt").write_bytes(original)
    (repository / ".gitignore").write_text("ignored-generated.txt\n", encoding="utf-8")
    _git_add(repository, "nested/tracked.txt", ".gitignore")
    _git_commit_fixture(repository)
    return repository, original


def _create_directory_alias(alias: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            pytest.skip(f"directory junction creation is unavailable: {completed.stderr}")
    else:
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink creation is unavailable: {exc}")


def _remove_directory_alias(alias: Path) -> None:
    if alias.is_symlink():
        alias.unlink()
    else:
        os.rmdir(alias)


def _validate_source_state_both(
    repository: Path,
    allowed_untracked: tuple[str, ...] = (),
    *,
    tracked_paths: int = 2,
    verified_blobs: int = 2,
    gitlinks: int = 0,
) -> None:
    audit_result = validate_repository_source_state(repository, allowed_untracked)
    release_result = openocd_release.verify_repository_source_state(
        repository, allowed_untracked
    )
    assert audit_result["tracked_paths"] == release_result["tracked_paths"] == tracked_paths
    assert audit_result["verified_blobs"] == release_result["verified_blobs"] == verified_blobs
    assert audit_result["gitlinks"] == release_result["gitlinks"] == gitlinks


def _assert_source_state_rejected_both(
    repository: Path,
    allowed_untracked: tuple[str, ...] = (),
    *,
    match: str | None = None,
) -> None:
    with pytest.raises(AuditFailure, match=match):
        validate_repository_source_state(repository, allowed_untracked)
    with pytest.raises(SystemExit, match=match):
        openocd_release.verify_repository_source_state(repository, allowed_untracked)


def _generated_source_fixture(tmp_path: Path) -> Path:
    repository = tmp_path / "generated-source"
    _init_git_repository(repository)
    (repository / ".gitignore").write_text(
        "\n".join(EXPECTED_GENERATED_SOURCE_PATHS[1:]) + "\n",
        encoding="utf-8",
    )
    (repository / "tracked.txt").write_bytes(b"tracked source bytes\n")
    _git_add(repository, ".gitignore", "tracked.txt")
    _git_commit_fixture(repository)
    for index, relative in enumerate(EXPECTED_GENERATED_SOURCE_PATHS, start=1):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"generated source input {index}\n".encode("ascii"))
    return repository


def _stage_generated_source_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "bound-source-stage"
) -> tuple[Path, Path, dict]:
    repository = _generated_source_fixture(tmp_path)
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    staged = tmp_path / name
    staged.mkdir()
    binding = openocd_release.copy_source_tree(repository, staged)
    return repository, staged, binding


def _validate_generated_source_topology_both(repository: Path) -> None:
    audit_result = validate_generated_source_topology(
        repository, EXPECTED_GENERATED_SOURCE_PATHS
    )
    release_result = openocd_release.validate_generated_source_topology(
        repository, openocd_release.GENERATED_SOURCE_PATHS
    )
    expected = {
        "ordinary_files": 3,
        "paths": list(EXPECTED_GENERATED_SOURCE_PATHS),
    }
    assert audit_result == release_result == expected


def _assert_generated_source_topology_rejected_both(
    repository: Path,
    *,
    match: str,
) -> None:
    with pytest.raises(AuditFailure, match=match):
        validate_generated_source_topology(repository, EXPECTED_GENERATED_SOURCE_PATHS)
    with pytest.raises(SystemExit, match=match):
        openocd_release.validate_generated_source_topology(
            repository, openocd_release.GENERATED_SOURCE_PATHS
        )


def test_strict_json_rejects_duplicate_keys() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "duplicate.json"
        path.write_text('{"schema": 1, "schema": 2}', encoding="utf-8")
        with pytest.raises(AuditFailure, match="duplicate JSON key"):
            load_json_strict(path)


def _provenance_fixture() -> tuple[dict, dict]:
    release_manifest = {
        "release": "agamemnon-openocd-test",
        "source_date_epoch": 1777198205,
        "openocd": {
            "repository": "https://review.openocd.org/openocd",
            "base_commit": "a" * 40,
            "gerrit_change": 9590,
            "gerrit_patchset": 2,
            "gerrit_commit": "b" * 40,
            "gerrit_ref": "refs/changes/90/9590/2",
            "patched_commit": "c" * 40,
            "patches": ["patches/one.patch", "patches/two.patch"],
        },
        "submodules": {"jimtcl": "d" * 40, "src/jtag/drivers/libjaylink": "e" * 40},
        "oracle": {
            "repository": "https://example.invalid/oracle.git",
            "commit": "f" * 40,
            "openocd_exe_sha256": "1" * 64,
            "redistribute": False,
            "purpose": "comparison only",
        },
    }
    source_identity = {
        "head": release_manifest["openocd"]["patched_commit"],
        "parent": release_manifest["openocd"]["base_commit"],
        "submodules": copy.deepcopy(release_manifest["submodules"]),
    }
    expected = derive_source_provenance(
        release_manifest,
        source_identity,
        {"patches/one.patch": "2" * 64, "patches/two.patch": "3" * 64},
    )
    return release_manifest, expected


def _set_nested(value: dict, path: tuple[str, ...], replacement: object) -> None:
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema",), 2),
        (("release",), "mutated-release"),
        (("official_repository",), "https://example.invalid/mutated.git"),
        (("official_base_commit",), "4" * 40),
        (("agamemnon_patched_commit",), "5" * 40),
        (("gerrit", "change"), 9591),
        (("gerrit", "patchset"), 3),
        (("gerrit", "commit"), "6" * 40),
        (("gerrit", "ref"), "refs/changes/90/9590/3"),
        (("patch_sha256", "patches/one.patch"), "7" * 64),
        (("patch_sha256", "patches/two.patch"), "8" * 64),
        (("submodules", "jimtcl"), "9" * 40),
        (("submodules", "src/jtag/drivers/libjaylink"), "0" * 40),
        (("source_date_epoch",), 1777198206),
        (("oracle", "repository"), "https://example.invalid/mutated-oracle.git"),
        (("oracle", "commit"), "a" * 40),
        (("oracle", "openocd_exe_sha256"), "b" * 64),
        (("oracle", "redistribute"), True),
        (("oracle", "purpose"), "redistributable"),
    ],
)
def test_provenance_rejects_every_mutated_leaf_value(
    tmp_path: Path, path: tuple[str, ...], replacement: object
) -> None:
    _, expected = _provenance_fixture()
    mutated = copy.deepcopy(expected)
    _set_nested(mutated, path, replacement)
    provenance_path = tmp_path / "AGAMEMNON-PROVENANCE.json"
    provenance_path.write_bytes(canonical_provenance_bytes(mutated))
    with pytest.raises(AuditFailure):
        validate_source_provenance_file(provenance_path, expected)
    with pytest.raises(SystemExit):
        openocd_release.validate_source_provenance_document(provenance_path, expected)


@pytest.mark.parametrize("object_path", [(), ("gerrit",), ("patch_sha256",), ("submodules",), ("oracle",)])
def test_provenance_rejects_extra_and_missing_keys(
    tmp_path: Path, object_path: tuple[str, ...]
) -> None:
    _, expected = _provenance_fixture()
    for mutation in ("extra", "missing"):
        mutated = copy.deepcopy(expected)
        target = mutated
        for key in object_path:
            target = target[key]
        if mutation == "extra":
            target["compile_authorized" if not object_path else "unexpected_authority"] = True
        else:
            target.pop(next(iter(target)))
        provenance_path = tmp_path / f"{mutation}-{len(object_path)}.json"
        provenance_path.write_bytes(canonical_provenance_bytes(mutated))
        with pytest.raises(AuditFailure):
            validate_source_provenance_file(provenance_path, expected)
        with pytest.raises(SystemExit):
            openocd_release.validate_source_provenance_document(provenance_path, expected)


@pytest.mark.parametrize(
    "needle",
    [
        '  "schema": 1,',
        '    "change": 9590,',
        '    "patches/one.patch": "' + "2" * 64 + '",',
        '    "jimtcl": "' + "d" * 40 + '",',
        '    "repository": "https://example.invalid/oracle.git",',
    ],
)
def test_provenance_rejects_duplicate_keys_at_every_object_scope(
    tmp_path: Path, needle: str
) -> None:
    _, expected = _provenance_fixture()
    canonical = canonical_provenance_bytes(expected).decode("utf-8")
    duplicate = canonical.replace(needle, f"{needle}\n{needle}", 1)
    provenance_path = tmp_path / "duplicate.json"
    provenance_path.write_bytes(duplicate.encode("utf-8"))
    with pytest.raises(AuditFailure, match="duplicate JSON key"):
        validate_source_provenance_file(provenance_path, expected)
    with pytest.raises(SystemExit, match="duplicate JSON key"):
        openocd_release.validate_source_provenance_document(provenance_path, expected)


@pytest.mark.parametrize("encoding_variant", ["compact", "sorted", "crlf"])
def test_provenance_rejects_noncanonical_ordering_and_whitespace(
    tmp_path: Path, encoding_variant: str
) -> None:
    _, expected = _provenance_fixture()
    if encoding_variant == "compact":
        raw = json.dumps(expected, separators=(",", ":")).encode("utf-8")
    elif encoding_variant == "sorted":
        raw = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode("utf-8")
    else:
        raw = canonical_provenance_bytes(expected).replace(b"\n", b"\r\n")
    provenance_path = tmp_path / f"{encoding_variant}.json"
    provenance_path.write_bytes(raw)
    with pytest.raises(AuditFailure, match="canonical JSON bytes"):
        validate_source_provenance_file(provenance_path, expected)
    with pytest.raises(SystemExit, match="canonical JSON bytes"):
        openocd_release.validate_source_provenance_document(provenance_path, expected)


def test_provenance_rejects_deletion(tmp_path: Path) -> None:
    _, expected = _provenance_fixture()
    missing = tmp_path / "AGAMEMNON-PROVENANCE.json"
    with pytest.raises(AuditFailure, match="cannot read strict JSON"):
        validate_source_provenance_file(missing, expected)
    with pytest.raises(SystemExit, match="cannot read strict JSON"):
        openocd_release.validate_source_provenance_document(missing, expected)


def test_provenance_derivation_rejects_oracle_authority_or_schema_expansion() -> None:
    release_manifest, _ = _provenance_fixture()
    identity = {
        "head": release_manifest["openocd"]["patched_commit"],
        "submodules": release_manifest["submodules"],
    }
    patch_hashes = {"patches/one.patch": "2" * 64, "patches/two.patch": "3" * 64}
    release_manifest["oracle"]["redistribute"] = True
    with pytest.raises(AuditFailure, match="redistribute must be false"):
        derive_source_provenance(release_manifest, identity, patch_hashes)
    release_manifest["oracle"]["redistribute"] = False
    release_manifest["oracle"]["compile_authorized"] = True
    with pytest.raises(AuditFailure, match="keys differ"):
        derive_source_provenance(release_manifest, identity, patch_hashes)


def test_release_verify_source_requires_provenance_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repository(tmp_path)
    release_manifest = openocd_release.manifest()
    identity = {
        "head": release_manifest["openocd"]["patched_commit"],
        "parent": release_manifest["openocd"]["base_commit"],
        "submodules": copy.deepcopy(release_manifest["submodules"]),
    }
    monkeypatch.setattr(openocd_release, "_verify_source_identity", lambda source, data: identity)
    monkeypatch.setattr(
        openocd_release,
        "_verify_all_repository_source_state",
        lambda source, data, root_untracked: {".": "fixture"},
    )
    patch_dir = tmp_path / "AGAMEMNON-PATCHES"
    patch_dir.mkdir()
    for relative in release_manifest["openocd"]["patches"]:
        (patch_dir / Path(relative).name).write_bytes(
            (openocd_release.HERE / relative).read_bytes()
        )
    (tmp_path / openocd_release.PROVENANCE_NAME).write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit, match="cannot read strict JSON"):
        openocd_release.verify_source(tmp_path)
    with pytest.raises(TypeError):
        openocd_release.verify_source(tmp_path, require_provenance=False)

    assert openocd_release._verify_source_before_provenance(tmp_path) == identity
    expected = openocd_release.source_provenance(
        tmp_path, data=release_manifest, identity=identity
    )
    (tmp_path / openocd_release.PROVENANCE_NAME).write_text(
        openocd_release.canonical_provenance_text(expected),
        encoding="utf-8",
        newline="",
    )
    assert openocd_release.verify_source(tmp_path) == identity


def test_source_state_rejects_skip_worktree_hiding_altered_bytes_and_restores(
    tmp_path: Path,
) -> None:
    repository, original = _source_state_fixture(tmp_path)
    _validate_source_state_both(repository)
    _git_fixture_command(repository, "update-index", "--skip-worktree", "--", "tracked.txt")
    (repository / "tracked.txt").write_bytes(b"hidden by skip-worktree\n")
    assert _git_fixture_command(repository, "status", "--porcelain").stdout == b""
    _assert_source_state_rejected_both(repository)
    _git_fixture_command(repository, "update-index", "--no-skip-worktree", "--", "tracked.txt")
    (repository / "tracked.txt").write_bytes(original)
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_rejects_assume_unchanged_hiding_altered_bytes_and_restores(
    tmp_path: Path,
) -> None:
    repository, original = _source_state_fixture(tmp_path)
    _git_fixture_command(repository, "update-index", "--assume-unchanged", "--", "tracked.txt")
    (repository / "tracked.txt").write_bytes(b"hidden by assume-unchanged\n")
    assert _git_fixture_command(repository, "status", "--porcelain").stdout == b""
    _assert_source_state_rejected_both(repository)
    _git_fixture_command(repository, "update-index", "--no-assume-unchanged", "--", "tracked.txt")
    (repository / "tracked.txt").write_bytes(original)
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_rejects_staged_replacement_and_restores(tmp_path: Path) -> None:
    repository, original = _source_state_fixture(tmp_path)
    (repository / "tracked.txt").write_bytes(b"staged replacement\n")
    _git_add(repository, "tracked.txt")
    _assert_source_state_rejected_both(repository)
    (repository / "tracked.txt").write_bytes(original)
    _git_add(repository, "tracked.txt")
    _validate_source_state_both(repository)


def test_source_state_rejects_intent_to_add_and_restores(tmp_path: Path) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    candidate = repository / "candidate.txt"
    candidate.write_text("intent to add\n", encoding="utf-8")
    _git_fixture_command(repository, "add", "--intent-to-add", "--", "candidate.txt")
    _assert_source_state_rejected_both(repository)
    _git_fixture_command(repository, "rm", "--cached", "--force", "--", "candidate.txt")
    candidate.unlink()
    _validate_source_state_both(repository)


def test_source_state_rejects_fsmonitor_valid_when_representable_and_restores(
    tmp_path: Path,
) -> None:
    repository, original = _source_state_fixture(tmp_path)
    command = subprocess.run(
        ["git", "-C", str(repository), "update-index", "--fsmonitor-valid", "--", "tracked.txt"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if command.returncode != 0:
        pytest.skip("this Git build cannot represent fsmonitor-valid safely")
    tagged = _git_fixture_command(repository, "ls-files", "-f", "-z").stdout
    if b"h tracked.txt\0" not in tagged:
        _git_fixture_command(
            repository, "update-index", "--no-fsmonitor-valid", "--", "tracked.txt"
        )
        pytest.skip("fsmonitor-valid bit was not persisted by this repository")
    (repository / "tracked.txt").write_bytes(b"hidden by fsmonitor-valid\n")
    assert _git_fixture_command(repository, "status", "--porcelain").stdout == b""
    _assert_source_state_rejected_both(repository)
    _git_fixture_command(repository, "update-index", "--no-fsmonitor-valid", "--", "tracked.txt")
    (repository / "tracked.txt").write_bytes(original)
    _validate_source_state_both(repository)


def test_source_state_rejects_staged_file_mode_change_and_restores(tmp_path: Path) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    _git_fixture_command(repository, "update-index", "--chmod=+x", "--", "tracked.txt")
    _assert_source_state_rejected_both(repository)
    _git_fixture_command(repository, "update-index", "--chmod=-x", "--", "tracked.txt")
    _validate_source_state_both(repository)


def test_source_state_rejects_worktree_symlink_type_change_when_representable(
    tmp_path: Path,
) -> None:
    repository, original = _source_state_fixture(tmp_path)
    tracked = repository / "tracked.txt"
    tracked.unlink()
    try:
        tracked.symlink_to(".gitignore")
    except OSError:
        tracked.write_bytes(original)
        pytest.skip("worktree symlink creation is not safely available")
    _assert_source_state_rejected_both(repository)
    tracked.unlink()
    tracked.write_bytes(original)
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


@pytest.mark.parametrize("mutation", ["missing", "dirty"])
def test_source_state_rejects_missing_or_dirty_tracked_file_and_restores(
    tmp_path: Path, mutation: str
) -> None:
    repository, original = _source_state_fixture(tmp_path)
    tracked = repository / "tracked.txt"
    if mutation == "missing":
        tracked.unlink()
    else:
        tracked.write_bytes(b"dirty worktree bytes\n")
    _assert_source_state_rejected_both(repository)
    tracked.write_bytes(original)
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_rejects_forbidden_untracked_and_allows_only_exact_paths(
    tmp_path: Path,
) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    forbidden = repository / "forbidden.txt"
    forbidden.write_text("forbidden\n", encoding="utf-8")
    _assert_source_state_rejected_both(repository)
    forbidden.unlink()

    visible = repository / "generated-visible.txt"
    ignored = repository / "ignored-generated.txt"
    visible.write_text("visible generated\n", encoding="utf-8")
    ignored.write_text("ignored generated\n", encoding="utf-8")
    allowed = ("generated-visible.txt", "ignored-generated.txt")
    _validate_source_state_both(repository, allowed)
    visible.unlink()
    ignored.unlink()
    _validate_source_state_both(repository)


def test_source_state_rejects_unmerged_index_stages_and_restores(tmp_path: Path) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    base = _git_fixture_command(repository, "rev-parse", "HEAD:tracked.txt").stdout.decode().strip()
    ours = _git_fixture_command(
        repository, "hash-object", "-w", "--stdin", input_bytes=b"ours\n"
    ).stdout.decode().strip()
    theirs = _git_fixture_command(
        repository, "hash-object", "-w", "--stdin", input_bytes=b"theirs\n"
    ).stdout.decode().strip()
    zero = "0" * len(base)
    index_info = (
        f"0 {zero}\ttracked.txt\n"
        f"100644 {base} 1\ttracked.txt\n"
        f"100644 {ours} 2\ttracked.txt\n"
        f"100644 {theirs} 3\ttracked.txt\n"
    ).encode("ascii")
    _git_fixture_command(repository, "update-index", "--index-info", input_bytes=index_info)
    _assert_source_state_rejected_both(repository)
    _git_add(repository, "tracked.txt")
    _validate_source_state_both(repository)


def test_source_state_rejects_outside_hardlink_and_restores(tmp_path: Path) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    outside_link = tmp_path / "outside-hardlink.txt"
    os.link(repository / "tracked.txt", outside_link)
    _assert_source_state_rejected_both(repository, match="exactly one hard link")
    outside_link.unlink()
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_rejects_inside_hardlink_before_untracked_gate_and_restores(
    tmp_path: Path,
) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    inside_link = repository / "inside-hardlink.txt"
    os.link(repository / "tracked.txt", inside_link)
    _assert_source_state_rejected_both(repository, match="exactly one hard link")
    inside_link.unlink()
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_requires_all_extra_hardlinks_removed_before_restoration(
    tmp_path: Path,
) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    inside_link = repository / "inside-hardlink.txt"
    outside_link = tmp_path / "outside-hardlink.txt"
    os.link(repository / "tracked.txt", inside_link)
    os.link(repository / "tracked.txt", outside_link)
    _assert_source_state_rejected_both(repository, match="exactly one hard link")
    outside_link.unlink()
    _assert_source_state_rejected_both(repository, match="exactly one hard link")
    inside_link.unlink()
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_rejects_tracked_ancestor_directory_alias_and_restores(
    tmp_path: Path,
) -> None:
    repository, _ = _nested_source_state_fixture(tmp_path)
    nested = repository / "nested"
    outside_nested = tmp_path / "outside-nested"
    nested.rename(outside_nested)
    _create_directory_alias(nested, outside_nested)
    try:
        _assert_source_state_rejected_both(repository, match="tracked path topology")
    finally:
        _remove_directory_alias(nested)
        outside_nested.rename(nested)
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(repository)


def test_source_state_rejects_repository_root_alias_and_accepts_exact_root(
    tmp_path: Path,
) -> None:
    repository, _ = _source_state_fixture(tmp_path)
    alias = tmp_path / "source-state-alias"
    _create_directory_alias(alias, repository)
    try:
        _assert_source_state_rejected_both(alias, match="repository root")
    finally:
        _remove_directory_alias(alias)
    _validate_source_state_both(repository)


def test_source_state_and_packaging_reject_tracked_symlink_without_following_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "symlink-source-state"
    _init_git_repository(repository)
    outside_target = tmp_path / "outside-target.txt"
    outside_target.write_bytes(b"outside target bytes are not source bytes\n")
    link = repository / "tracked-link"
    try:
        link.symlink_to(outside_target)
    except OSError as exc:
        pytest.skip(f"worktree symlink creation is unavailable: {exc}")
    (repository / ".gitignore").write_text("ignored-generated.txt\n", encoding="utf-8")
    _git_add(repository, "tracked-link", ".gitignore")
    staged = _git_fixture_command(repository, "ls-files", "--stage", "tracked-link").stdout
    if not staged.startswith(b"120000 "):
        pytest.skip("this Git worktree cannot represent a genuine tracked symlink")
    _git_commit_fixture(repository)
    link_bytes = _git_fixture_command(repository, "show", "HEAD:tracked-link").stdout

    _assert_source_state_rejected_both(repository, match="not allowed by the exact source inventory")
    outside_target.write_bytes(b"mutated target bytes must remain irrelevant\n")
    _assert_source_state_rejected_both(repository, match="not allowed by the exact source inventory")
    outside_target.unlink()
    _assert_source_state_rejected_both(repository, match="not allowed by the exact source inventory")

    staged_tree = tmp_path / "source-stage"
    staged_tree.mkdir()
    for index, relative in enumerate(EXPECTED_GENERATED_SOURCE_PATHS, start=1):
        generated = repository / relative
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_bytes(f"generated source input {index}\n".encode("ascii"))
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [
            Path("tracked-link"),
            *(Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS),
        ],
    )
    with pytest.raises(SystemExit, match="not allowed by the exact source inventory"):
        openocd_release.copy_source_tree(repository, staged_tree)
    assert list(staged_tree.rglob("*")) == []

    link.unlink()
    link.write_bytes(link_bytes)
    _assert_source_state_rejected_both(repository, match="tracked symlink type differs")
    link.unlink()
    link.symlink_to(os.fsdecode(link_bytes))
    _git_fixture_command(repository, "update-index", "--refresh")
    _assert_source_state_rejected_both(repository, match="not allowed by the exact source inventory")


def test_source_state_rejects_gitlink_without_exact_repository_identity_or_topology(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "gitlink-source-state"
    _init_git_repository(repository)
    (repository / ".gitignore").write_text("ignored-generated.txt\n", encoding="utf-8")
    module = repository / "module"
    _init_git_repository(module)
    (module / "module.txt").write_bytes(b"module bytes\n")
    _git_add(module, "module.txt")
    _git_commit_fixture(module)
    _git_add(repository, ".gitignore", "module")
    staged = _git_fixture_command(repository, "ls-files", "--stage", "module").stdout
    assert staged.startswith(b"160000 ")
    _git_commit_fixture(repository)

    _validate_source_state_both(
        repository, tracked_paths=2, verified_blobs=1, gitlinks=1
    )
    (module / "module.txt").write_bytes(b"new module commit\n")
    _git_add(module, "module.txt")
    _git_commit_fixture(module)
    _assert_source_state_rejected_both(repository, match="gitlink HEAD differs")
    _git_fixture_command(module, "switch", "--detach", "HEAD^")
    _validate_source_state_both(
        repository, tracked_paths=2, verified_blobs=1, gitlinks=1
    )

    outside_module = tmp_path / "outside-module"
    module.rename(outside_module)
    module.mkdir()
    (module / "module.txt").write_bytes(b"module bytes\n")
    _assert_source_state_rejected_both(repository, match="Git repository identity differs")
    (module / "module.txt").unlink()
    module.rmdir()

    _create_directory_alias(module, outside_module)
    try:
        _assert_source_state_rejected_both(repository, match="tracked path topology")
    finally:
        _remove_directory_alias(module)
        outside_module.rename(module)
    _git_fixture_command(repository, "update-index", "--refresh")
    _validate_source_state_both(
        repository, tracked_paths=2, verified_blobs=1, gitlinks=1
    )


def test_generated_source_topology_and_archive_staging_accept_exact_ordinary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    _validate_source_state_both(
        repository, EXPECTED_GENERATED_SOURCE_PATHS
    )
    _validate_generated_source_topology_both(repository)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    staged = tmp_path / "positive-source-stage"
    staged.mkdir()
    openocd_release.copy_source_tree(repository, staged)
    assert {
        path.relative_to(staged).as_posix(): path.read_bytes()
        for path in staged.rglob("*")
        if path.is_file()
    } == {
        relative: (repository / relative).read_bytes()
        for relative in EXPECTED_GENERATED_SOURCE_PATHS
    }


@pytest.mark.parametrize("relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_generated_source_hardlinks_fail_both_verifiers_and_staging_then_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    generated = repository / relative
    original = generated.read_bytes()
    outside = tmp_path / (generated.name + ".outside-hardlink")
    outside.write_bytes(original)
    generated.unlink()
    os.link(outside, generated)
    assert os.lstat(generated).st_nlink == 2

    _assert_generated_source_topology_rejected_both(
        repository, match="exactly one hard link"
    )
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    staged = tmp_path / "hardlink-source-stage"
    staged.mkdir()
    with pytest.raises(SystemExit, match="exactly one hard link"):
        openocd_release.copy_source_tree(repository, staged)
    assert list(staged.rglob("*")) == []

    generated.unlink()
    generated.write_bytes(original)
    outside.unlink()
    _validate_generated_source_topology_both(repository)


@pytest.mark.parametrize("relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_generated_source_symlinks_fail_without_following_then_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    generated = repository / relative
    original = generated.read_bytes()
    outside = tmp_path / (generated.name + ".outside-target")
    outside.write_bytes(original)
    generated.unlink()
    try:
        generated.symlink_to(outside)
    except OSError as exc:
        generated.write_bytes(original)
        pytest.skip(f"worktree symlink creation is unavailable: {exc}")

    _assert_generated_source_topology_rejected_both(
        repository, match="not an ordinary file"
    )
    outside.write_bytes(b"mutated outside bytes must remain irrelevant\n")
    _assert_generated_source_topology_rejected_both(
        repository, match="not an ordinary file"
    )
    outside.unlink()
    _assert_generated_source_topology_rejected_both(
        repository, match="not an ordinary file"
    )
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    staged = tmp_path / "symlink-source-stage"
    staged.mkdir()
    with pytest.raises(SystemExit, match="not an ordinary file"):
        openocd_release.copy_source_tree(repository, staged)
    assert list(staged.rglob("*")) == []

    generated.unlink()
    generated.write_bytes(original)
    _validate_generated_source_topology_both(repository)


def test_generated_patch_ancestor_alias_fails_both_verifiers_and_staging_then_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    patch_directory = repository / "AGAMEMNON-PATCHES"
    outside_directory = tmp_path / "outside-generated-patches"
    patch_directory.rename(outside_directory)
    _create_directory_alias(patch_directory, outside_directory)
    try:
        _assert_generated_source_topology_rejected_both(
            repository, match="path topology"
        )
        monkeypatch.setattr(
            openocd_release,
            "tracked_files",
            lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
        )
        staged = tmp_path / "alias-source-stage"
        staged.mkdir()
        with pytest.raises(SystemExit, match="path topology"):
            openocd_release.copy_source_tree(repository, staged)
        assert list(staged.rglob("*")) == []
    finally:
        _remove_directory_alias(patch_directory)
        outside_directory.rename(patch_directory)
    _validate_generated_source_topology_both(repository)


def test_archive_staging_rechecks_generated_link_count_around_copy_and_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    _validate_generated_source_topology_both(repository)
    target_relative = EXPECTED_GENERATED_SOURCE_PATHS[1]
    target = repository / target_relative
    outside = tmp_path / "copy-boundary-hardlink.patch"
    original_copy = openocd_release._release_copy_verified_stream
    injected = False

    def mutate_during_copy(source_stream, destination_stream, relative):
        nonlocal injected
        if relative == target_relative and not injected:
            os.link(target, outside)
            injected = True
        return original_copy(source_stream, destination_stream, relative)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", mutate_during_copy
    )
    staged = tmp_path / "mutation-source-stage"
    staged.mkdir()
    with pytest.raises(SystemExit, match="exactly one hard link"):
        openocd_release.copy_source_tree(repository, staged)
    assert injected
    assert os.lstat(target).st_nlink == 2

    outside.unlink()
    _validate_generated_source_topology_both(repository)


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_rejects_temporary_substitution_while_opening_nofollow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    target = repository / target_relative
    original = target.read_bytes()
    original_stat = os.lstat(target)
    outside = tmp_path / (target.name + ".open-substitute")
    outside.write_bytes(b"temporary open substitution bytes\n")
    stash = tmp_path / (target.name + ".open-original-stash")
    original_open = openocd_release._release_open_readonly_nofollow
    target_open_count = 0
    injected = False

    def substitute_while_opening(path, label):
        nonlocal target_open_count, injected
        if Path(path) == target:
            target_open_count += 1
            if target_open_count == 2:
                target.rename(stash)
                target.symlink_to(outside)
                injected = True
                try:
                    return original_open(path, label)
                finally:
                    target.unlink()
                    stash.rename(target)
        return original_open(path, label)

    ordered = list(EXPECTED_GENERATED_SOURCE_PATHS)
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in ordered],
    )
    monkeypatch.setattr(
        openocd_release, "_release_open_readonly_nofollow", substitute_while_opening
    )
    staged = tmp_path / "open-substitution-source-stage"
    staged.mkdir()
    with pytest.raises(SystemExit):
        openocd_release.copy_source_tree(repository, staged)

    restored_stat = os.lstat(target)
    assert injected and target_open_count == 2
    assert target.read_bytes() == original
    assert (restored_stat.st_dev, restored_stat.st_ino) == (
        original_stat.st_dev,
        original_stat.st_ino,
    )
    assert restored_stat.st_nlink == 1
    assert not any(path.is_file() for path in staged.rglob("*"))
    _validate_generated_source_topology_both(repository)


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_binds_temporary_path_substitution_to_open_source_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    target = repository / target_relative
    original = target.read_bytes()
    original_stat = os.lstat(target)
    outside = tmp_path / (target.name + ".temporary-substitute")
    outside.write_bytes(b"temporary substituted source bytes\n")
    stash = tmp_path / (target.name + ".original-stash")
    original_copy = openocd_release._release_copy_verified_stream
    injected = False

    def substitute_during_copy(source_stream, destination_stream, relative):
        nonlocal injected
        if relative == target_relative and not injected:
            target.rename(stash)
            target.symlink_to(outside)
            injected = True
            try:
                return original_copy(source_stream, destination_stream, relative)
            finally:
                target.unlink()
                stash.rename(target)
        return original_copy(source_stream, destination_stream, relative)

    ordered = list(EXPECTED_GENERATED_SOURCE_PATHS)
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in ordered],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", substitute_during_copy
    )
    staged = tmp_path / "temporary-substitution-source-stage"
    staged.mkdir()
    openocd_release.copy_source_tree(repository, staged)

    staged_target = staged / target_relative
    restored_stat = os.lstat(target)
    assert injected
    assert target.read_bytes() == original
    assert (restored_stat.st_dev, restored_stat.st_ino) == (
        original_stat.st_dev,
        original_stat.st_ino,
    )
    assert restored_stat.st_nlink == 1
    assert not staged_target.is_symlink()
    assert os.lstat(staged_target).st_nlink == 1
    assert staged_target.read_bytes() == original
    _validate_generated_source_topology_both(repository)


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_rejects_in_place_byte_change_and_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    target = repository / target_relative
    original = target.read_bytes()
    original_stat = os.lstat(target)
    mutated = bytes(byte ^ 0x5A for byte in original)
    assert mutated != original and len(mutated) == len(original)
    original_copy = openocd_release._release_copy_verified_stream
    injected = False

    def mutate_during_copy(source_stream, destination_stream, relative):
        nonlocal injected
        if relative == target_relative and not injected:
            target.write_bytes(mutated)
            injected = True
            try:
                return original_copy(source_stream, destination_stream, relative)
            finally:
                target.write_bytes(original)
        return original_copy(source_stream, destination_stream, relative)

    ordered = list(EXPECTED_GENERATED_SOURCE_PATHS)
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in ordered],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", mutate_during_copy
    )
    staged = tmp_path / "byte-mutation-source-stage"
    staged.mkdir()
    with pytest.raises(SystemExit, match="bytes changed during staging"):
        openocd_release.copy_source_tree(repository, staged)

    restored_stat = os.lstat(target)
    assert injected
    assert target.read_bytes() == original
    assert (restored_stat.st_dev, restored_stat.st_ino) == (
        original_stat.st_dev,
        original_stat.st_ino,
    )
    assert restored_stat.st_nlink == 1
    assert not any(path.is_file() for path in staged.rglob("*"))
    _validate_generated_source_topology_both(repository)

    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", original_copy
    )
    restored_stage = tmp_path / "restored-byte-source-stage"
    restored_stage.mkdir()
    openocd_release.copy_source_tree(repository, restored_stage)
    assert {
        path.relative_to(restored_stage).as_posix(): path.read_bytes()
        for path in restored_stage.rglob("*")
        if path.is_file()
    } == {
        relative: (repository / relative).read_bytes()
        for relative in EXPECTED_GENERATED_SOURCE_PATHS
    }


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_independently_rejects_staged_byte_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    target = repository / target_relative
    original = target.read_bytes()
    mutated = bytes(byte ^ 0xA5 for byte in original)
    assert mutated != original and len(mutated) == len(original)
    staged = tmp_path / "staged-byte-mutation-source-stage"
    staged.mkdir()
    staged_target = staged / target_relative
    original_copy = openocd_release._release_copy_verified_stream
    injected = False

    def mutate_staged_copy(source_stream, destination_stream, relative):
        nonlocal injected
        copied_hash, copied_size = original_copy(
            source_stream, destination_stream, relative
        )
        if relative == target_relative and not injected:
            destination_stream.flush()
            staged_target.write_bytes(mutated)
            injected = True
        return copied_hash, copied_size

    ordered = list(EXPECTED_GENERATED_SOURCE_PATHS)
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in ordered],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", mutate_staged_copy
    )
    with pytest.raises(SystemExit, match="staged source archive output bytes differ"):
        openocd_release.copy_source_tree(repository, staged)

    assert injected
    assert target.read_bytes() == original
    assert not any(path.is_file() for path in staged.rglob("*"))
    _validate_generated_source_topology_both(repository)


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_independently_rejects_staged_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    target = repository / target_relative
    original = target.read_bytes()
    staged = tmp_path / "staged-hardlink-source-stage"
    staged.mkdir()
    staged_target = staged / target_relative
    outside = tmp_path / (target.name + ".staged-hardlink")
    original_copy = openocd_release._release_copy_verified_stream
    injected = False

    def hardlink_staged_copy(source_stream, destination_stream, relative):
        nonlocal injected
        copied_hash, copied_size = original_copy(
            source_stream, destination_stream, relative
        )
        if relative == target_relative and not injected:
            destination_stream.flush()
            os.link(staged_target, outside)
            injected = True
        return copied_hash, copied_size

    ordered = list(EXPECTED_GENERATED_SOURCE_PATHS)
    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in ordered],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", hardlink_staged_copy
    )
    with pytest.raises(SystemExit, match="must have exactly one hard link"):
        openocd_release.copy_source_tree(repository, staged)

    assert injected
    assert target.read_bytes() == original
    assert not any(path.is_file() for path in staged.rglob("*"))
    assert outside.read_bytes() == original
    outside.unlink()
    _validate_generated_source_topology_both(repository)


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_failure_is_whole_tree_transactional_and_retry_clean_in_natural_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "natural-order-transaction-stage"
    staged.mkdir()
    original_copy = openocd_release._release_copy_verified_stream
    reached = []

    def fail_after_copy(source_stream, destination_stream, relative):
        result = original_copy(source_stream, destination_stream, relative)
        reached.append(relative)
        if relative == target_relative:
            raise SystemExit(f"injected natural-order failure: {relative}")
        return result

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", fail_after_copy
    )
    with pytest.raises(SystemExit, match="injected natural-order failure"):
        openocd_release.copy_source_tree(repository, staged)

    target_index = EXPECTED_GENERATED_SOURCE_PATHS.index(target_relative)
    assert reached == list(EXPECTED_GENERATED_SOURCE_PATHS[: target_index + 1])
    assert list(staged.iterdir()) == []

    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", original_copy
    )
    binding = openocd_release.copy_source_tree(repository, staged)
    assert set(binding["members"]) == set(EXPECTED_GENERATED_SOURCE_PATHS)
    assert {
        path.relative_to(staged).as_posix(): path.read_bytes()
        for path in staged.rglob("*")
        if path.is_file()
    } == {
        relative: (repository / relative).read_bytes()
        for relative in EXPECTED_GENERATED_SOURCE_PATHS
    }


@pytest.mark.parametrize("fail_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_archive_staging_file_substitution_at_final_disposition_is_blocked_or_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "final-file-disposition-stage"
    staged.mkdir()
    original_copy = openocd_release._release_copy_verified_stream
    original_disposition = openocd_release._release_mark_windows_handle_for_deletion
    replacement = b"unrelated final-disposition replacement\n"
    attempted = []
    blocked = []
    substituted = []

    def fail_after_copy(source_stream, destination_stream, relative):
        result = original_copy(source_stream, destination_stream, relative)
        if relative == fail_relative:
            raise SystemExit(f"injected final-disposition failure: {relative}")
        return result

    def substitute_at_disposition(custody, path, kind):
        path = Path(path)
        if kind == "file" and not attempted:
            attempted.append(path)
            stash = tmp_path / "final-disposition-original.stash"
            try:
                path.rename(stash)
            except OSError:
                blocked.append(path)
            else:
                path.write_bytes(replacement)
                substituted.append(path)
        return original_disposition(custody, path, kind)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", fail_after_copy
    )
    monkeypatch.setattr(
        openocd_release,
        "_release_mark_windows_handle_for_deletion",
        substitute_at_disposition,
    )
    with pytest.raises(SystemExit, match="injected final-disposition failure"):
        openocd_release.copy_source_tree(repository, staged)

    if os.name == "nt":
        assert attempted and blocked and not substituted
        assert list(staged.iterdir()) == []
    else:
        # No destructive rollback is claimed where open handles do not pin a
        # pathname entry.  The original transaction output is preserved.
        assert not attempted
        assert any(path.is_file() for path in staged.rglob("*"))


@pytest.mark.parametrize("fail_relative", EXPECTED_GENERATED_SOURCE_PATHS[1:])
def test_archive_staging_directory_substitution_at_final_disposition_is_blocked_or_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_relative: str
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "final-directory-disposition-stage"
    staged.mkdir()
    original_copy = openocd_release._release_copy_verified_stream
    original_disposition = openocd_release._release_mark_windows_handle_for_deletion
    directory = staged / "AGAMEMNON-PATCHES"
    replacement_marker = b"unrelated directory replacement\n"
    attempted = False
    blocked = False
    substituted = False

    def fail_after_copy(source_stream, destination_stream, relative):
        result = original_copy(source_stream, destination_stream, relative)
        if relative == fail_relative:
            raise SystemExit(f"injected final-directory failure: {relative}")
        return result

    def substitute_at_disposition(custody, path, kind):
        nonlocal attempted, blocked, substituted
        path = Path(path)
        if kind == "directory" and path == directory and not attempted:
            attempted = True
            stash = tmp_path / "final-directory-original.stash"
            try:
                path.rename(stash)
            except OSError:
                blocked = True
            else:
                path.mkdir()
                (path / "replacement.marker").write_bytes(replacement_marker)
                substituted = True
        return original_disposition(custody, path, kind)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", fail_after_copy
    )
    monkeypatch.setattr(
        openocd_release,
        "_release_mark_windows_handle_for_deletion",
        substitute_at_disposition,
    )
    with pytest.raises(SystemExit, match="injected final-directory failure"):
        openocd_release.copy_source_tree(repository, staged)

    if os.name == "nt":
        assert attempted and blocked and not substituted
        assert list(staged.iterdir()) == []
    else:
        assert not attempted
        assert directory.is_dir()


def test_archive_staging_cleanup_failure_preserves_output_and_fresh_root_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "cleanup-failure-stage"
    staged.mkdir()
    fresh = tmp_path / "cleanup-failure-fresh-stage"
    fresh.mkdir()
    original_copy = openocd_release._release_copy_verified_stream
    original_disposition = openocd_release._release_mark_windows_handle_for_deletion
    failed_cleanup_path = []

    def fail_after_last_copy(source_stream, destination_stream, relative):
        result = original_copy(source_stream, destination_stream, relative)
        if relative == EXPECTED_GENERATED_SOURCE_PATHS[-1]:
            raise SystemExit("injected primary failure before cleanup")
        return result

    def fail_one_cleanup(custody, path, kind):
        if kind == "file" and not failed_cleanup_path:
            failed_cleanup_path.append(Path(path))
            raise SystemExit("injected exact cleanup failure")
        return original_disposition(custody, path, kind)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", fail_after_last_copy
    )
    monkeypatch.setattr(
        openocd_release,
        "_release_mark_windows_handle_for_deletion",
        fail_one_cleanup,
    )
    with pytest.raises(SystemExit, match="^injected primary failure before cleanup"):
        openocd_release.copy_source_tree(repository, staged)

    assert any(path.is_file() for path in staged.rglob("*"))
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", original_copy
    )
    monkeypatch.setattr(
        openocd_release,
        "_release_mark_windows_handle_for_deletion",
        original_disposition,
    )
    binding = openocd_release.copy_source_tree(repository, fresh)
    assert set(binding["members"]) == set(EXPECTED_GENERATED_SOURCE_PATHS)


def test_private_package_workspace_preserves_outer_tree_without_generic_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "private-package-workspace"
    recursive_cleanup_called = False

    def make_private_workspace(*, prefix):
        assert prefix == "agamemnon-openocd-"
        workspace.mkdir()
        return str(workspace)

    def reject_recursive_cleanup(*_args, **_kwargs):
        nonlocal recursive_cleanup_called
        recursive_cleanup_called = True
        raise AssertionError("generic recursive cleanup must not run")

    monkeypatch.setattr(openocd_release.tempfile, "mkdtemp", make_private_workspace)
    monkeypatch.setattr(openocd_release.shutil, "rmtree", reject_recursive_cleanup)
    with pytest.raises(RuntimeError, match="injected package failure"):
        with openocd_release._release_private_package_workspace() as private_root:
            (private_root / "preserved.txt").write_bytes(b"preserve me\n")
            raise RuntimeError("injected package failure")

    assert not recursive_cleanup_called
    assert (workspace / "preserved.txt").read_bytes() == b"preserve me\n"


def test_exact_cleanup_custodies_close_at_most_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "exact-cleanup-handle-ownership-stage"
    staged.mkdir()
    original_copy = openocd_release._release_copy_verified_stream
    original_close = openocd_release._release_close_directory_custody
    close_counts = {}

    def fail_after_last_copy(source_stream, destination_stream, relative):
        result = original_copy(source_stream, destination_stream, relative)
        if relative == EXPECTED_GENERATED_SOURCE_PATHS[-1]:
            raise SystemExit("injected handle-ownership failure")
        return result

    def count_close(custody):
        if custody is not None and not custody.get("closed"):
            key = (os.fspath(custody.get("path", "")), custody.get("handle"))
            close_counts[key] = close_counts.get(key, 0) + 1
        return original_close(custody)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", fail_after_last_copy
    )
    monkeypatch.setattr(
        openocd_release, "_release_close_directory_custody", count_close
    )
    with pytest.raises(SystemExit, match="injected handle-ownership failure"):
        openocd_release.copy_source_tree(repository, staged)

    assert close_counts
    assert set(close_counts.values()) == {1}
    if os.name == "nt":
        assert list(staged.iterdir()) == []


def test_archive_staging_rollback_never_unlinks_a_leaf_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "replacement-safe-stage"
    staged.mkdir()
    original_copy = openocd_release._release_copy_verified_stream
    prior_relative = EXPECTED_GENERATED_SOURCE_PATHS[0]
    fail_relative = EXPECTED_GENERATED_SOURCE_PATHS[-1]
    prior = staged / prior_relative
    original_stash = tmp_path / "transaction-created-original.stash"
    replacement = b"unrelated replacement must survive rollback\n"
    injected = False

    def replace_prior_then_fail(source_stream, destination_stream, relative):
        nonlocal injected
        result = original_copy(source_stream, destination_stream, relative)
        if relative == fail_relative and not injected:
            prior.rename(original_stash)
            prior.write_bytes(replacement)
            injected = True
            raise SystemExit("injected failure after leaf replacement")
        return result

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", replace_prior_then_fail
    )
    with pytest.raises(SystemExit, match="failure after leaf replacement"):
        openocd_release.copy_source_tree(repository, staged)

    assert injected
    assert prior.read_bytes() == replacement
    assert original_stash.read_bytes() == (repository / prior_relative).read_bytes()
    assert not (staged / EXPECTED_GENERATED_SOURCE_PATHS[-1]).exists()
    with pytest.raises(SystemExit, match="staging root must be empty"):
        openocd_release.copy_source_tree(repository, staged)


def test_archive_staging_parent_redirection_is_impossible_or_rejected_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "parent-custody-stage"
    staged.mkdir()
    parent = staged / "AGAMEMNON-PATCHES"
    parent_stash = tmp_path / "staging-parent-original.stash"
    replacement_marker = b"replacement parent marker\n"
    original_create = openocd_release._release_create_file_in_directory
    attempted = False
    blocked = False

    def redirect_parent_before_create(custody, path, leaf_name, flags, mode):
        nonlocal attempted, blocked
        if Path(path).parent == parent and not attempted:
            attempted = True
            try:
                parent.rename(parent_stash)
            except OSError:
                blocked = True
            else:
                parent.mkdir()
                (parent / "replacement.marker").write_bytes(replacement_marker)
        return original_create(custody, path, leaf_name, flags, mode)

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release,
        "_release_create_file_in_directory",
        redirect_parent_before_create,
    )
    if os.name == "nt":
        binding = openocd_release.copy_source_tree(repository, staged)
        assert attempted and blocked
        assert set(binding["members"]) == set(EXPECTED_GENERATED_SOURCE_PATHS)
        assert not parent_stash.exists()
    else:
        with pytest.raises(SystemExit, match="staging parent identity changed"):
            openocd_release.copy_source_tree(repository, staged)
        assert attempted and not blocked
        assert (parent / "replacement.marker").read_bytes() == replacement_marker
        assert parent_stash.is_dir()


def test_archive_staging_rejects_an_injected_extra_member_without_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "extra-member-stage"
    staged.mkdir()
    injected = staged / "unrelated-replacement.txt"
    injected_bytes = b"not owned by the staging transaction\n"
    original_copy = openocd_release._release_copy_verified_stream

    def inject_after_last_copy(source_stream, destination_stream, relative):
        result = original_copy(source_stream, destination_stream, relative)
        if relative == EXPECTED_GENERATED_SOURCE_PATHS[-1]:
            injected.write_bytes(injected_bytes)
        return result

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", inject_after_last_copy
    )
    with pytest.raises(SystemExit, match="staging file inventory differs"):
        openocd_release.copy_source_tree(repository, staged)
    assert injected.read_bytes() == injected_bytes
    assert not (staged / EXPECTED_GENERATED_SOURCE_PATHS[0]).exists()


def test_bound_source_archive_consumes_exact_staged_handle_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, staged, binding = _stage_generated_source_fixture(
        tmp_path, monkeypatch, "positive-bound-source-stage"
    )
    archive = tmp_path / "positive-bound-source.tar.gz"
    openocd_release.normalized_tar_gz(staged, archive, 1777198205, binding)

    with tarfile.open(archive, "r:gz") as source_tar:
        observed = {
            Path(member.name).relative_to(staged.name).as_posix(): source_tar.extractfile(
                member
            ).read()
            for member in source_tar.getmembers()
            if member.isfile()
        }
    assert observed == {
        relative: (repository / relative).read_bytes()
        for relative in EXPECTED_GENERATED_SOURCE_PATHS
    }


def test_bound_source_archive_rejects_an_unexpected_unbound_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository, staged, binding = _stage_generated_source_fixture(
        tmp_path, monkeypatch, "bound-extra-member-stage"
    )
    extra = staged / "unexpected-member.txt"
    extra.write_bytes(b"must not enter the source archive\n")
    with pytest.raises(SystemExit, match="unexpected or unsafe member"):
        openocd_release.normalized_tar_gz(
            staged,
            tmp_path / "bound-extra-member.tar.gz",
            1777198205,
            binding,
        )


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
@pytest.mark.parametrize("mutation", ("append", "truncate", "same-size"))
def test_bound_source_archive_rejects_post_consumption_byte_mutation_at_every_order_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_relative: str,
    mutation: str,
) -> None:
    _repository, staged, binding = _stage_generated_source_fixture(
        tmp_path, monkeypatch, f"bound-{mutation}-stage"
    )
    target = staged / target_relative
    original = target.read_bytes()
    original_consume = openocd_release._release_consume_bound_tar_stream
    injected = False

    def mutate_after_consumption(out, info, stream, relative):
        nonlocal injected
        result = original_consume(out, info, stream, relative)
        if relative == target_relative and not injected:
            if mutation == "append":
                target.write_bytes(original + b"appended")
            elif mutation == "truncate":
                target.write_bytes(original[:-1])
            else:
                target.write_bytes(bytes(byte ^ 0xA5 for byte in original))
            injected = True
        return result

    monkeypatch.setattr(
        openocd_release,
        "_release_consume_bound_tar_stream",
        mutate_after_consumption,
    )
    archive = tmp_path / f"bound-{mutation}.tar.gz"
    with pytest.raises(SystemExit, match="changed during tar consumption"):
        openocd_release.normalized_tar_gz(staged, archive, 1777198205, binding)
    assert injected


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS)
def test_bound_source_archive_rejects_leaf_replacement_after_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    _repository, staged, binding = _stage_generated_source_fixture(
        tmp_path, monkeypatch, "bound-leaf-replacement-stage"
    )
    target = staged / target_relative
    original = target.read_bytes()
    stash = tmp_path / (target.name + ".archive-original-stash")
    replacement = b"archive leaf replacement\n"
    original_consume = openocd_release._release_consume_bound_tar_stream
    injected = False

    def replace_after_consumption(out, info, stream, relative):
        nonlocal injected
        result = original_consume(out, info, stream, relative)
        if relative == target_relative and not injected:
            target.rename(stash)
            target.write_bytes(replacement)
            injected = True
        return result

    monkeypatch.setattr(
        openocd_release,
        "_release_consume_bound_tar_stream",
        replace_after_consumption,
    )
    with pytest.raises(SystemExit, match="changed during tar consumption"):
        openocd_release.normalized_tar_gz(
            staged,
            tmp_path / "bound-leaf-replacement.tar.gz",
            1777198205,
            binding,
        )
    assert injected
    assert target.read_bytes() == replacement
    assert stash.read_bytes() == original


@pytest.mark.parametrize("target_relative", EXPECTED_GENERATED_SOURCE_PATHS[1:])
def test_bound_source_archive_parent_redirection_is_impossible_or_rejected_during_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_relative: str
) -> None:
    _repository, staged, binding = _stage_generated_source_fixture(
        tmp_path, monkeypatch, "bound-parent-redirection-stage"
    )
    target = staged / target_relative
    parent = target.parent
    stash = tmp_path / (parent.name + ".archive-parent-stash")
    replacement = b"archive parent replacement\n"
    original_consume = openocd_release._release_consume_bound_tar_stream
    attempted = False
    blocked = False

    def redirect_parent_during_consumption(out, info, stream, relative):
        nonlocal attempted, blocked
        result = original_consume(out, info, stream, relative)
        if relative == target_relative and not attempted:
            attempted = True
            try:
                parent.rename(stash)
            except OSError:
                blocked = True
            else:
                parent.mkdir()
                (parent / Path(target_relative).name).write_bytes(replacement)
        return result

    monkeypatch.setattr(
        openocd_release,
        "_release_consume_bound_tar_stream",
        redirect_parent_during_consumption,
    )
    archive = tmp_path / "bound-parent-redirection.tar.gz"
    if os.name == "nt":
        openocd_release.normalized_tar_gz(staged, archive, 1777198205, binding)
        assert attempted and blocked
        assert not stash.exists()
    else:
        with pytest.raises(SystemExit, match="parent identity changed"):
            openocd_release.normalized_tar_gz(
                staged, archive, 1777198205, binding
            )
        assert attempted and not blocked
        assert (parent / Path(target_relative).name).read_bytes() == replacement
        assert stash.is_dir()


def test_package_never_rewrites_secured_generated_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "package-source"
    source.mkdir()
    (source / "COPYING").write_bytes(b"license\n")
    prefix = tmp_path / "package-prefix"
    executable = prefix / "bin" / "openocd.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"not executed\n")
    output = tmp_path / "package-output"
    package_workspace = tmp_path / "package-private-workspace"
    secured_provenance = b"secured copied provenance sentinel\n"
    observed = False

    monkeypatch.setattr(openocd_release, "verify_source", lambda _source: None)

    def make_package_workspace(*, prefix):
        assert prefix == "agamemnon-openocd-"
        package_workspace.mkdir()
        return str(package_workspace)

    monkeypatch.setattr(openocd_release.tempfile, "mkdtemp", make_package_workspace)
    monkeypatch.setattr(
        openocd_release, "source_provenance", lambda _source: {"frozen": True}
    )
    monkeypatch.setattr(openocd_release, "make_sbom", lambda _root, _platform: None)
    monkeypatch.setattr(openocd_release, "write_file_manifest", lambda _root: None)

    def fake_copy_source_tree(_source, destination):
        destination = Path(destination)
        (destination / openocd_release.PROVENANCE_NAME).write_bytes(
            secured_provenance
        )
        return {"schema": 1, "root_identity": (0, 0), "members": {}}

    def fake_zip(_root, archive, _epoch):
        Path(archive).write_bytes(b"binary archive\n")

    def inspect_source_tar(root, archive, _epoch, source_binding=None):
        nonlocal observed
        assert source_binding is not None
        assert (Path(root) / openocd_release.PROVENANCE_NAME).read_bytes() == secured_provenance
        observed = True
        Path(archive).write_bytes(b"source archive\n")

    monkeypatch.setattr(openocd_release, "copy_source_tree", fake_copy_source_tree)
    monkeypatch.setattr(openocd_release, "normalized_zip", fake_zip)
    monkeypatch.setattr(openocd_release, "normalized_tar_gz", inspect_source_tar)
    openocd_release.package("windows-test", source, prefix, output)
    assert observed


def test_staging_stream_failure_preserves_primary_error_without_double_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _generated_source_fixture(tmp_path)
    staged = tmp_path / "descriptor-ownership-stage"
    staged.mkdir()

    def primary_failure(_source_stream, _destination_stream, _relative):
        raise SystemExit("primary stream failure")

    monkeypatch.setattr(
        openocd_release,
        "tracked_files",
        lambda _source: [Path(item) for item in EXPECTED_GENERATED_SOURCE_PATHS],
    )
    monkeypatch.setattr(
        openocd_release, "_release_copy_verified_stream", primary_failure
    )
    with pytest.raises(SystemExit, match="^primary stream failure$"):
        openocd_release.copy_source_tree(repository, staged)
    assert list(staged.iterdir()) == []


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


def test_zero_extra_directory_gate_rejects_named_and_random_dirs_in_all_scopes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        jimtcl = root / "jimtcl"
        libjaylink = root / "src/jtag/drivers/libjaylink"
        _init_git_repository(root)
        _init_git_repository(jimtcl)
        _init_git_repository(libjaylink)

        (jimtcl / "tests").mkdir()
        (jimtcl / "tests/fixture.tcl").write_text("# tracked\n", encoding="utf-8")
        _git_add(jimtcl, "tests/fixture.tcl")
        _git_commit_fixture(jimtcl)
        (libjaylink / "src").mkdir()
        (libjaylink / "src/fixture.c").write_text("/* tracked */\n", encoding="utf-8")
        _git_add(libjaylink, "src/fixture.c")
        _git_commit_fixture(libjaylink)

        (root / ".gitignore").write_text("build-scanbuild/\n", encoding="utf-8")
        (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        _git_add(root, ".gitignore", "tracked.txt", "jimtcl", "src/jtag/drivers/libjaylink")

        patch_directory = root / "AGAMEMNON-PATCHES"
        patch_directory.mkdir()
        expected_root_files: dict[str, str] = {}
        patch_names = (
            "0001-target-riscv-DM-access-on-a-DAP.patch",
            "0002-target-riscv-fix-nested-ADIv5-config.patch",
        )
        for number, patch_name in enumerate(patch_names, start=1):
            relative = f"AGAMEMNON-PATCHES/{patch_name}"
            path = root / relative
            path.write_bytes(f"patch-{number}".encode("ascii"))
            expected_root_files[relative] = sha256_file(path)
        expected_scopes = {
            ".": expected_root_files,
            "jimtcl": {},
            "src/jtag/drivers/libjaylink": {},
        }
        validate_zero_extra_directories(root, expected_scopes)

        nested_fake_git = patch_directory / ".git"
        nested_fake_git.mkdir()
        with pytest.raises(AuditFailure, match="zero-extra-directory inventory differs"):
            validate_zero_extra_directories(root, expected_scopes)
        nested_fake_git.rmdir()

        build_scanbuild = root / "build-scanbuild"
        build_scanbuild.mkdir()
        with pytest.raises(AuditFailure, match="zero-extra-directory inventory differs in \\."):
            validate_zero_extra_directories(root, expected_scopes)
        build_scanbuild.rmdir()

        jim_tempdir = jimtcl / "tests/tempdir"
        jim_tempdir.mkdir()
        with pytest.raises(AuditFailure, match="differs in jimtcl"):
            validate_zero_extra_directories(root, expected_scopes)
        jim_tempdir.rmdir()

        for scope, repository in (
            (".", root),
            ("jimtcl", jimtcl),
            ("src/jtag/drivers/libjaylink", libjaylink),
        ):
            random_directory = repository / "random-empty-9f14"
            random_directory.mkdir()
            with pytest.raises(AuditFailure, match=f"differs in {re.escape(scope)}"):
                validate_zero_extra_directories(root, expected_scopes)
            random_directory.rmdir()


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
        downgraded_policy = json.loads(json.dumps(occurrence_policy))
        downgraded_policy[0]["disposition"] = "EXTERNAL_DESTINATION_DYNAMIC"
        downgraded_policy[0]["resolved_directory_names"] = []
        with pytest.raises(AuditFailure, match="cannot be downgraded"):
            validate_directory_creation_occurrences(
                occurrences,
                downgraded_policy,
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
            + "BUILD_DIR := build\nMKDIR := mkdir -p\n$(MKDIR) $(BUILD_DIR)\n",
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
        dynamic_policy = occurrence_policy + [
            {
                "source": "testing/examples/example/makefile",
                "line": 3,
                "expression": "MKDIR := mkdir -p",
                "kind": "LITERAL_MKDIR",
                "disposition": "ALIAS_DEFINITION_ONLY",
                "resolved_directory_names": [],
            },
            {
                "source": "testing/examples/example/makefile",
                "line": 4,
                "expression": "$(MKDIR) $(BUILD_DIR)",
                "kind": "MKDIR_ALIAS_USE",
                "disposition": "FORBIDDEN_ANCESTOR_DIRECTORY",
                "resolved_directory_names": ["build"],
            },
        ]
        bound_makefile = (example / "makefile").read_text(encoding="utf-8")
        dynamic_occurrences = discover_directory_creation_occurrences(root)
        validate_directory_creation_occurrences(
            dynamic_occurrences,
            dynamic_policy,
            [".dep", "build"],
            [],
            {"testing/examples/example/makefile": bound_makefile},
        )
        downgraded_dynamic_policy = json.loads(json.dumps(dynamic_policy))
        downgraded_dynamic_policy[-1]["disposition"] = "EXTERNAL_DESTINATION_DYNAMIC"
        downgraded_dynamic_policy[-1]["resolved_directory_names"] = []
        with pytest.raises(AuditFailure, match="cannot be downgraded"):
            validate_directory_creation_occurrences(
                dynamic_occurrences,
                downgraded_dynamic_policy,
                [".dep", "build"],
                [],
                {"testing/examples/example/makefile": bound_makefile},
            )


def test_exact_two_ignored_patch_exceptions_pass_and_all_drift_rejects() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _init_git_repository(root)
        jimtcl = root / "jimtcl"
        libjaylink = root / "src/jtag/drivers/libjaylink"
        _init_git_repository(jimtcl)
        _init_git_repository(libjaylink)
        (jimtcl / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        _git_add(jimtcl, "tracked.txt")
        _git_commit_fixture(jimtcl)
        (libjaylink / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        _git_add(libjaylink, "tracked.txt")
        _git_commit_fixture(libjaylink)
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
        _git_add(root, ".gitignore", "jimtcl", "src/jtag/drivers/libjaylink")
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
            "secondary_build_rule_review": {
                "security_boundary": False,
                "completeness_claimed": False,
                "primary_boundary": "ZERO_EXTRA_DIRECTORY_FROM_GIT_TRACKED_PARENTS",
                "recorded_mechanisms": [],
            },
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
