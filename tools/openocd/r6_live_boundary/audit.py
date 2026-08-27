#!/usr/bin/env python3
"""Read-only Phase-0 audit for the R6 OpenOCD live boundary.

This module deliberately has no build, process-launch, USB, debugger, or device
enumeration path.  It proves only that the frozen source and policy inputs are
the exact material reviewed for the later implementation phases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "phase0_manifest.json"
TOOL_OBSERVATION_PATH = HERE / "tool_observation.json"

LOADER_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(LoadLibrary(?:Ex)?(?:A|W)?|LoadPackagedLibrary|LdrLoadDll|GetProcAddress)"
    r"\s*\("
)
ADAPTER_RE = re.compile(r"\[\[([A-Za-z0-9_]+)\],\s*\[")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
DLL_RE = re.compile(r"^[a-z0-9_.-]+\.dll$")


class AuditFailure(RuntimeError):
    """A fail-closed Phase-0 invariant did not hold."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AuditFailure(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json_strict(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"cannot read strict JSON {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AuditFailure(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def git_text(source: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if completed.returncode != 0:
        raise AuditFailure(
            f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditFailure(message)


def require_exact_keys(actual: Mapping[str, Any], expected: Iterable[str], label: str) -> None:
    expected_set = set(expected)
    actual_set = set(actual)
    require(
        actual_set == expected_set,
        f"{label} keys differ: missing={sorted(expected_set - actual_set)} "
        f"unexpected={sorted(actual_set - expected_set)}",
    )


def ordered_offsets(text: str, markers: Sequence[str], label: str) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    for marker in markers:
        offset = text.find(marker, cursor)
        if offset < 0:
            raise AuditFailure(f"{label}: absent or out-of-order marker: {marker}")
        offsets.append(offset)
        cursor = offset + len(marker)
    return offsets


def extract_adapter_names(configure_text: str) -> list[str]:
    start = configure_text.find("# Adapter drivers")
    end = configure_text.find("m4_define([OPTIONAL_LIBRARIES]", start)
    require(start >= 0 and end > start, "configure adapter inventory boundaries absent")
    names = ADAPTER_RE.findall(configure_text[start:end])
    require(names, "configure adapter inventory is empty")
    require(len(names) == len(set(names)), "configure adapter inventory has duplicates")
    return names


def derive_adapter_flags(enabled: Sequence[str], disabled: Sequence[str]) -> list[str]:
    flags = [f"--enable-{name.replace('_', '-')}" for name in sorted(enabled)]
    flags.extend(f"--disable-{name.replace('_', '-')}" for name in sorted(disabled))
    return flags


def validate_adapter_plan(
    inventory: Sequence[str], enabled: Sequence[str], disabled: Sequence[str]
) -> None:
    require(len(enabled) == len(set(enabled)), "enabled adapter plan has duplicates")
    require(len(disabled) == len(set(disabled)), "disabled adapter plan has duplicates")
    require(set(enabled).isdisjoint(disabled), "adapter enable/disable plans overlap")
    require(
        set(enabled) | set(disabled) == set(inventory),
        "adapter plan does not cover exact inventory",
    )


def validate_backend_inventory(source: Path, inventory: Mapping[str, Any]) -> None:
    implementations = inventory["implementations"]
    selected = inventory["selected_real_implementations"]
    excluded = inventory["excluded_real_implementations"]
    require(len(selected) == len(set(selected)), "selected backend inventory has duplicates")
    require(len(excluded) == len(set(excluded)), "excluded backend inventory has duplicates")
    require(set(selected).isdisjoint(excluded), "selected/excluded backend inventories overlap")
    require(set(selected) | set(excluded) == set(implementations), "backend inventory is incomplete")
    require(selected == ["usb_bulk"], "Phase-0 may select only the USB-bulk backend")

    core_text = (source / inventory["core_source"]).read_text(encoding="utf-8", errors="strict")
    makefile_text = (source / inventory["makefile"]).read_text(encoding="utf-8", errors="strict")
    for name, backend in implementations.items():
        implementation_text = (source / backend["source"]).read_text(
            encoding="utf-8", errors="strict"
        )
        require(backend["symbol"] in implementation_text, f"backend symbol absent: {name}")
        require(f"if {backend['condition']}" in makefile_text, f"backend make condition absent: {name}")
        require(
            Path(backend["source"]).name in makefile_text,
            f"backend source membership absent: {name}",
        )
        require(
            f"#if {backend['build_define']} == 0" in core_text,
            f"inert backend stub condition absent: {name}",
        )
        require(backend["symbol"] in core_text, f"backend core symbol absent: {name}")


def scan_prebuild_artifacts(root: Path, suffixes: Sequence[str]) -> list[str]:
    lowered_suffixes = tuple(item.lower() for item in suffixes)
    artifacts: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name.lower().endswith(lowered_suffixes):
            artifacts.append(path.relative_to(root).as_posix())
    return sorted(artifacts)


def scan_loader_calls(root: Path, roots: Sequence[str], suffixes: Sequence[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    suffix_set = set(suffixes)
    for relative_root in roots:
        base = root / relative_root
        require(base.is_dir(), f"loader scan root absent: {relative_root}")
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            if path.suffix not in suffix_set:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError) as exc:
                raise AuditFailure(f"cannot scan loader calls in {path}: {exc}") from exc
            apis = sorted(set(LOADER_CALL_RE.findall(text)))
            if apis:
                result[path.relative_to(root).as_posix()] = apis
    return result


def scan_forbidden_literals(
    root: Path,
    roots: Sequence[str],
    suffixes: Sequence[str],
    literals: Sequence[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    suffix_set = set(suffixes)
    lowered_literals = [item.lower() for item in literals]
    for relative_root in roots:
        base = root / relative_root
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            if path.suffix not in suffix_set:
                continue
            text = path.read_text(encoding="utf-8", errors="strict").lower()
            matches = sorted(literal for literal in lowered_literals if literal in text)
            if matches:
                result[path.relative_to(root).as_posix()] = matches
    return result


def validate_pe_import_inventory(
    inventory: Mapping[str, Any],
    policy: Mapping[str, Any],
    exact_system_dlls: Sequence[str] | None = None,
) -> None:
    require_exact_keys(
        inventory,
        ["schema", "image_sha256", "direct_imports", "delay_imports"],
        "PE inventory",
    )
    require(inventory["schema"] == 1, "PE inventory schema must be 1")
    require(
        isinstance(inventory["image_sha256"], str)
        and HEX64_RE.fullmatch(inventory["image_sha256"]) is not None,
        "PE image_sha256 must be lowercase hexadecimal",
    )
    for field in ("direct_imports", "delay_imports"):
        imports = inventory[field]
        require(isinstance(imports, list), f"PE {field} must be an array")
        require(all(isinstance(item, str) for item in imports), f"PE {field} must contain strings")
        require(all(DLL_RE.fullmatch(item) is not None for item in imports), f"PE {field} has invalid DLL name")
        require(len(imports) == len(set(imports)), f"PE {field} contains duplicates")
        require(imports == sorted(imports), f"PE {field} must be sorted")

    delay_allowed = sorted(policy["delay_imports_allowed"])
    require(inventory["delay_imports"] == delay_allowed, "PE delay imports violate exact policy")
    require(exact_system_dlls is not None, "exact system DLL allowlist is not frozen")
    system = set(exact_system_dlls)
    require(all(DLL_RE.fullmatch(item) is not None for item in system), "invalid system DLL allowlist entry")
    adjacent = set(policy["adjacent_dlls_allowed"])
    prefixes = tuple(policy["api_set_prefixes"])
    allowed_direct = system | adjacent
    unknown = [
        item
        for item in inventory["direct_imports"]
        if item not in allowed_direct and not item.startswith(prefixes)
    ]
    require(not unknown, f"PE direct imports not allowed: {unknown}")


def _tracked_files(source: Path) -> list[str]:
    output = git_text(source, "ls-files", "--recurse-submodules", "-z")
    return [item for item in output.split("\0") if item]


def _verify_source_identity(source: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    expected = manifest["source"]
    head = git_text(source, "rev-parse", "HEAD").strip()
    parent = git_text(source, "rev-parse", "HEAD^").strip()
    tree = git_text(source, "rev-parse", "HEAD^{tree}").strip()
    gerrit_type = git_text(source, "cat-file", "-t", expected["gerrit_commit"]).strip()
    gerrit_parent = git_text(source, "rev-parse", f"{expected['gerrit_commit']}^").strip()
    require(head == expected["patched_commit"], "patched source commit differs")
    require(parent == expected["base_commit"], "patched source parent differs")
    require(tree == expected["tree"], "patched source tree differs")
    require(gerrit_type == "commit", "frozen Gerrit object is absent or not a commit")
    require(gerrit_parent == expected["base_commit"], "frozen Gerrit parent differs")

    submodules: dict[str, str] = {}
    for line in git_text(source, "submodule", "status").splitlines():
        match = re.fullmatch(r"[ +\-U]?([0-9a-f]{40})\s+(\S+)(?:\s+.*)?", line)
        require(match is not None, f"cannot parse submodule status: {line}")
        submodules[match.group(2)] = match.group(1)
    require(submodules == expected["submodules"], "submodule identities differ")

    files = _tracked_files(source)
    inventory = expected["tracked_file_inventory"]
    counts = {
        "count": len(files),
        "c_files": sum(path.endswith(".c") for path in files),
        "h_files": sum(path.endswith(".h") for path in files),
        "automake_files": sum(path.endswith("Makefile.am") for path in files),
    }
    require(counts == inventory, f"tracked source inventory differs: {counts}")
    forbidden_suffixes = tuple(manifest["source_inventory"]["forbidden_prebuild_suffixes"])
    forbidden = sorted(path for path in files if path.lower().endswith(forbidden_suffixes))
    require(not forbidden, f"tracked prebuild artifacts present: {forbidden}")
    filesystem_artifacts = scan_prebuild_artifacts(source, forbidden_suffixes)
    require(not filesystem_artifacts, f"source-tree prebuild artifacts present: {filesystem_artifacts}")

    provenance = load_json_strict(source / "AGAMEMNON-PROVENANCE.json")
    require(provenance["schema"] == 1, "prepared-source provenance schema differs")
    require(provenance["official_repository"] == expected["repository"], "provenance repository differs")
    require(provenance["official_base_commit"] == expected["base_commit"], "provenance base differs")
    require(provenance["agamemnon_patched_commit"] == expected["patched_commit"], "provenance head differs")
    require(
        provenance["gerrit"]
        == {
            "change": expected["gerrit_change"],
            "patchset": expected["gerrit_patchset"],
            "commit": expected["gerrit_commit"],
            "ref": expected["gerrit_ref"],
        },
        "prepared-source Gerrit provenance differs",
    )
    require(provenance["submodules"] == expected["submodules"], "provenance submodules differ")
    expected_patch_hashes: dict[str, str] = {}
    for relative, expected_hash in manifest["deterministic_inputs"].items():
        marker = "tools/openocd/patches/"
        if relative.startswith(marker):
            patch_name = relative[len("tools/openocd/") :]
            expected_patch_hashes[patch_name] = expected_hash
            copied_patch = source / "AGAMEMNON-PATCHES" / Path(relative).name
            require(sha256_file(copied_patch) == expected_hash, f"prepared patch copy differs: {relative}")
    require(provenance["patch_sha256"] == expected_patch_hashes, "provenance patch hashes differ")

    untracked = git_text(source, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    require(
        untracked == ["?? AGAMEMNON-PROVENANCE.json"],
        f"prepared source has unexpected visible worktree state: {untracked}",
    )
    return {
        "head": head,
        "parent": parent,
        "tree": tree,
        "gerrit_commit": expected["gerrit_commit"],
        "gerrit_parent": gerrit_parent,
        "submodules": submodules,
        "counts": counts,
        "prebuild_artifacts": filesystem_artifacts,
    }


def run_audit(source: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    source = source.resolve()
    repo_root = repo_root.resolve()
    require(source.is_dir(), f"source directory absent: {source}")
    manifest = load_json_strict(repo_root / "tools/openocd/r6_live_boundary/phase0_manifest.json")
    observation = load_json_strict(repo_root / "tools/openocd/r6_live_boundary/tool_observation.json")

    require(manifest["schema"] == 1, "Phase-0 manifest schema must be 1")
    require(manifest["status"] == "SOURCE_INVENTORY_ONLY_COMPILE_REFUSED", "unexpected Phase-0 state")
    for field in ("compile_authorized", "openocd_execution_authorized", "hardware_contact_authorized"):
        require(manifest[field] is False, f"{field} must remain false")
    require(manifest["blockers"], "Phase-0 must retain explicit blockers")
    require(observation["source_prepared_only"] is True, "tool observation is not source-only")
    require(observation["build_attempted"] is False, "tool observation claims a build")
    require(observation["openocd_executed"] is False, "tool observation claims OpenOCD execution")
    require(observation["build_allowed"] is False, "tool observation permits a build")
    require(observation["blocking_mismatches"], "version drift must fail closed")

    for relative, expected_hash in manifest["deterministic_inputs"].items():
        actual_hash = sha256_file(repo_root / relative)
        require(actual_hash == expected_hash, f"deterministic input hash differs: {relative}")

    source_identity = _verify_source_identity(source, manifest)
    source_inventory = manifest["source_inventory"]
    for relative in source_inventory["required_paths"]:
        require((source / relative).is_file(), f"required source path absent: {relative}")
    for relative, symbols in source_inventory["required_symbols"].items():
        text = (source / relative).read_text(encoding="utf-8", errors="strict")
        for symbol in symbols:
            require(symbol in text, f"required symbol absent in {relative}: {symbol}")

    configure_text = (source / "configure.ac").read_text(encoding="utf-8", errors="strict")
    adapters = extract_adapter_names(configure_text)
    configure_plan = manifest["configure_plan"]
    enabled = configure_plan["enabled_adapters"]
    disabled = configure_plan["disabled_adapters"]
    validate_adapter_plan(adapters, enabled, disabled)
    require(enabled == ["cmsis_dap_v2"], "Phase-0 may enable only CMSIS-DAP v2")
    adapter_flags = derive_adapter_flags(enabled, disabled)

    backend_inventory = manifest["backend_inventory"]
    validate_backend_inventory(source, backend_inventory)
    object_plan = manifest["object_inventory_plan"]
    require(object_plan["phase0_compiled_objects"] == [], "Phase-0 contains compiled objects")
    require(
        object_plan["source_tree_prebuild_artifacts_expected"] == [],
        "Phase-0 expects source-tree artifacts",
    )
    require(object_plan["final_object_inventory_frozen"] is False, "object inventory unexpectedly frozen")
    require(object_plan["archive_member_inventory_frozen"] is False, "archive inventory unexpectedly frozen")
    require(
        sorted(object_plan["required_openocd_source_stems"])
        == sorted(Path(path).stem for path in source_inventory["planned_adapter_sources"]),
        "object-plan source stems differ from planned adapter sources",
    )
    require(
        sorted(object_plan["excluded_backend_source_stems"])
        == sorted(Path(backend_inventory["implementations"][name]["source"]).stem for name in backend_inventory["excluded_real_implementations"]),
        "excluded backend object plan differs",
    )

    loader = manifest["loader_scan"]
    calls = scan_loader_calls(source, loader["roots"], loader["source_suffixes"])
    expected_calls = {
        path: sorted(disposition["apis"])
        for path, disposition in loader["expected_path_dispositions"].items()
    }
    require(calls == expected_calls, f"loader call inventory differs: {calls}")
    literals = scan_forbidden_literals(
        source,
        loader["roots"],
        loader["source_suffixes"],
        loader["forbidden_dll_literals"],
    )
    require(not literals, f"forbidden DLL literals found: {literals}")
    for relative in source_inventory["planned_adapter_sources"]:
        text = (source / relative).read_text(encoding="utf-8", errors="strict")
        require(not LOADER_CALL_RE.findall(text), f"loader API in planned source: {relative}")
        lowered = text.lower()
        require(
            not any(literal.lower() in lowered for literal in loader["forbidden_dll_literals"]),
            f"forbidden DLL literal in planned source: {relative}",
        )

    gate = manifest["gate_order"]
    main_text = (source / gate["entry_file"]).read_text(encoding="utf-8", errors="strict")
    entry_offsets = ordered_offsets(main_text, gate["entry_markers_in_order"], gate["entry_file"])
    require(gate["gate_symbol"] not in main_text, "unreviewed R6 live gate already present")
    require(gate["implementation_expected"] is False, "Phase-0 unexpectedly expects a live gate")
    require(entry_offsets[0] < entry_offsets[1], "main gate insertion window is invalid")
    openocd_text = (source / gate["openocd_file"]).read_text(encoding="utf-8", errors="strict")
    ordered_offsets(openocd_text, gate["openocd_main_markers_in_order"], "openocd_main")
    ordered_offsets(openocd_text, gate["openocd_thread_markers_in_order"], "openocd_thread")

    require(configure_plan["final_linker_flags_frozen"] is False, "Phase-0 linker policy unexpectedly frozen")
    require(configure_plan["libusb_winusb_only_patch_frozen"] is False, "Phase-0 libusb patch unexpectedly frozen")
    require(manifest["pe_import_policy"]["exact_system_dlls_frozen"] is False, "Phase-0 imports unexpectedly frozen")

    return {
        "status": "PASS_PHASE0_SOURCE_INVENTORY_COMPILE_REFUSED",
        "source": source_identity,
        "adapters": {
            "inventory_count": len(adapters),
            "enabled": enabled,
            "disabled_count": len(disabled),
            "derived_flags": adapter_flags,
        },
        "loader_calls": calls,
        "forbidden_literals": literals,
        "backend_inventory": {
            "selected_real_implementations": backend_inventory["selected_real_implementations"],
            "excluded_real_implementations": backend_inventory["excluded_real_implementations"],
            "final_object_membership_frozen": False,
        },
        "object_inventory": {
            "phase0_compiled_objects": [],
            "source_tree_prebuild_artifacts": source_identity["prebuild_artifacts"],
            "final_object_inventory_frozen": False,
        },
        "compile_authorized": False,
        "openocd_execution_authorized": False,
        "hardware_contact_authorized": False,
        "blocking_package_mismatches": observation["blocking_mismatches"],
        "remaining_blockers": manifest["blockers"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="prepared OpenOCD source tree")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="valve repository root")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_audit(args.source, args.repo_root)
    except AuditFailure as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
