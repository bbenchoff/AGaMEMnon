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

LOADER_IDENTIFIERS = (
    "GetProcAddress",
    "GetProcAddressA",
    "GetProcAddressW",
    "Jim_LoadLibrary",
    "LdrLoadDll",
    "LoadLibrary",
    "LoadLibraryA",
    "LoadLibraryExA",
    "LoadLibraryExW",
    "LoadLibraryW",
    "LoadPackagedLibrary",
    "Win32_LoadLibrary",
    "dlopen",
    "dlsym",
    "memdbDlOpen",
    "memdbDlSym",
    "osGetProcAddressA",
    "osLoadLibraryA",
    "osLoadLibraryW",
    "osLoadPackagedLibrary",
    "rbuVfsDlOpen",
    "rbuVfsDlSym",
    "sqlite3OsDlOpen",
    "sqlite3OsDlSym",
    "unixDlOpen",
    "unixDlSym",
    "winDlOpen",
    "winDlSym",
    "xDlOpen",
    "xDlSym",
)
DYNAMIC_IDENTIFIER_FAMILY_PATTERN = (
    r"\b(?:(?:[A-Za-z_]\w*)?(?:dlopen|dlsym)\w*|"
    r"(?:[A-Za-z_]\w*)?(?:Load(?:Packaged)?Library|GetProcAddress)[A-Za-z0-9_]*)\b"
)
DYNAMIC_IDENTIFIER_FAMILY_RE = re.compile(
    DYNAMIC_IDENTIFIER_FAMILY_PATTERN, re.IGNORECASE
)
LOADER_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(
        sorted((re.escape(name) for name in LOADER_IDENTIFIERS), key=len, reverse=True)
    ) + r")\s*\("
)
C_NONCODE_RE = re.compile(
    r"//[^\n\r]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
    re.DOTALL,
)
DECLARATION_PREFIX_RE = re.compile(
    r"^(?:(?:extern|static|inline|JIM_EXPORT|SQLITE_PRIVATE|SQLITE_API)\s+)*"
    r"(?:const\s+)?(?:struct\s+[A-Za-z_]\w*\s+|enum\s+[A-Za-z_]\w*\s+|"
    r"[A-Za-z_]\w*\s*)(?:\*+\s*)?$"
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


def verify_file_binding(path: Path, expected_hash: str, label: str) -> None:
    require(HEX64_RE.fullmatch(expected_hash) is not None, f"invalid bound hash: {label}")
    actual_hash = sha256_file(path)
    require(actual_hash == expected_hash, f"deterministic input hash differs: {label}")


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


def _matches_artifact_name(
    name: str, suffixes: Sequence[str], name_regexes: Sequence[str]
) -> bool:
    lowered_suffixes = tuple(item.lower() for item in suffixes)
    return name.lower().endswith(lowered_suffixes) or any(
        re.search(pattern, name) is not None for pattern in name_regexes
    )


def scan_build_artifacts(
    root: Path,
    suffixes: Sequence[str],
    name_regexes: Sequence[str],
    directory_names: Sequence[str],
    directory_prefixes: Sequence[str],
    allowed_files: Sequence[str] = (),
    exact_file_paths: Sequence[str] = (),
) -> dict[str, list[str]]:
    allowed = set(allowed_files)
    exact_files = {path.lower() for path in exact_file_paths}
    forbidden_directory_names = {name.lower() for name in directory_names}
    forbidden_directory_prefixes = tuple(prefix.lower() for prefix in directory_prefixes)
    artifacts: list[str] = []
    directories: list[str] = []
    for path in root.rglob("*"):
        if ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            lowered = path.name.lower()
            if lowered in forbidden_directory_names or lowered.startswith(forbidden_directory_prefixes):
                directories.append(relative)
        elif (
            path.is_file()
            and relative not in allowed
            and (
                relative.lower() in exact_files
                or _matches_artifact_name(path.name, suffixes, name_regexes)
            )
        ):
            artifacts.append(relative)
    return {"files": sorted(artifacts), "directories": sorted(directories)}


def _git_check_ignored_paths(repository: Path, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    payload = "\0".join(paths) + "\0"
    completed = subprocess.run(
        ["git", "-C", str(repository), "check-ignore", "--no-index", "-z", "--stdin"],
        input=payload,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if completed.returncode not in (0, 1):
        raise AuditFailure(f"git check-ignore failed: {completed.stderr.strip()}")
    return sorted(path for path in completed.stdout.split("\0") if path)


def ignored_untracked_files(repository: Path) -> list[str]:
    output = git_text(
        repository,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
    )
    return sorted(path for path in output.split("\0") if path)


def ignored_untracked_directories(
    repository: Path, excluded_subtrees: Sequence[str] = ()
) -> list[str]:
    excluded = tuple(path.rstrip("/") + "/" for path in excluded_subtrees)
    candidates: list[str] = []
    for path in repository.rglob("*"):
        if not path.is_dir() or ".git" in path.parts:
            continue
        relative = path.relative_to(repository).as_posix()
        if any(relative == item.rstrip("/") or relative.startswith(item) for item in excluded):
            continue
        candidates.append(relative + "/")
    return _git_check_ignored_paths(repository, candidates)


def validate_artifact_rule_inventory(
    source: Path,
    artifact_policy: Mapping[str, Any],
    rule_inventory: Mapping[str, Any],
    expected_tree: str,
) -> dict[str, Any]:
    require_exact_keys(
        rule_inventory,
        [
            "schema",
            "kind",
            "source_tree",
            "rule_sources",
            "exact_product_paths",
            "derived_directory_names",
            "ignored_untracked_expected",
        ],
        "artifact rule inventory",
    )
    require(rule_inventory["schema"] == 1, "artifact rule inventory schema must be 1")
    require(
        rule_inventory["kind"] == "R6_OPENOCD_DERIVED_ARTIFACT_RULE_INVENTORY",
        "artifact rule inventory kind differs",
    )
    require(rule_inventory["source_tree"] == expected_tree, "artifact rule source tree differs")

    source_text: dict[str, str] = {}
    for relative, expected_hash in rule_inventory["rule_sources"].items():
        path = source / relative
        require(path.is_file(), f"artifact rule source absent: {relative}")
        require(sha256_file(path) == expected_hash, f"artifact rule source hash differs: {relative}")
        source_text[relative] = path.read_text(encoding="utf-8", errors="strict")

    products = rule_inventory["exact_product_paths"]
    require_exact_keys(products, artifact_policy["exact_file_paths"], "derived exact products")
    for product, specification in products.items():
        require_exact_keys(
            specification,
            ["ignore_source", "ignore_rule", "evidence"],
            f"derived product {product}",
        )
        ignore_source = specification["ignore_source"]
        ignore_rule = specification["ignore_rule"]
        require(ignore_source in source_text, f"unbound ignore source for {product}")
        ignore_lines = {
            line.strip()
            for line in source_text[ignore_source].splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        require(ignore_rule in ignore_lines, f"ignore rule absent for {product}: {ignore_rule}")
        for evidence in specification["evidence"]:
            require_exact_keys(evidence, ["source", "marker"], f"product evidence {product}")
            require(evidence["source"] in source_text, f"unbound evidence source for {product}")
            require(
                evidence["marker"] in source_text[evidence["source"]],
                f"product evidence absent for {product}: {evidence['marker']}",
            )
        ignore_root_relative = Path(ignore_source).parent.as_posix()
        ignore_root_relative = "." if ignore_root_relative == "." else ignore_root_relative
        ignore_root = source if ignore_root_relative == "." else source / ignore_root_relative
        local_product = Path(product).relative_to(ignore_root_relative).as_posix() \
            if ignore_root_relative != "." else product
        require(
            _git_check_ignored_paths(ignore_root, [local_product]) == [local_product],
            f"Git does not derive ignored product: {product}",
        )

    derived_directories = rule_inventory["derived_directory_names"]
    require(
        set(derived_directories).issubset(artifact_policy["directory_names"]),
        "derived build directories are absent from broad scanner policy",
    )
    for directory_name, evidence_items in derived_directories.items():
        require(evidence_items, f"derived directory lacks evidence: {directory_name}")
        for evidence in evidence_items:
            require_exact_keys(evidence, ["source", "marker"], f"directory evidence {directory_name}")
            require(evidence["source"] in source_text, f"unbound directory source: {directory_name}")
            require(
                evidence["marker"] in source_text[evidence["source"]],
                f"directory evidence absent for {directory_name}: {evidence['marker']}",
            )

    expected_scopes = rule_inventory["ignored_untracked_expected"]
    require_exact_keys(
        expected_scopes,
        [".", "jimtcl", "src/jtag/drivers/libjaylink"],
        "ignored-untracked scope inventory",
    )
    ignored_summary: dict[str, dict[str, Any]] = {}
    nested_scopes = {
        ".": ["jimtcl", "src/jtag/drivers/libjaylink"],
        "jimtcl": [],
        "src/jtag/drivers/libjaylink": [],
    }
    for scope, expected_files in expected_scopes.items():
        repository = source if scope == "." else source / scope
        actual_files = ignored_untracked_files(repository)
        require(actual_files == sorted(expected_files), f"ignored untracked files differ in {scope}: {actual_files}")
        for relative, expected_hash in expected_files.items():
            require(
                sha256_file(repository / relative) == expected_hash,
                f"ignored prepared metadata hash differs: {scope}/{relative}",
            )
        ignored_directories = ignored_untracked_directories(repository, nested_scopes[scope])
        require(not ignored_directories, f"ignored untracked directories present in {scope}: {ignored_directories}")
        ignored_summary[scope] = {
            "files": actual_files,
            "directories": ignored_directories,
        }
    return {
        "rule_sources": len(source_text),
        "exact_products": len(products),
        "derived_directories": len(derived_directories),
        "ignored_untracked": ignored_summary,
    }


def _blank_noncode(match: re.Match[str]) -> str:
    return "".join(character if character in "\r\n" else " " for character in match.group(0))


def _matching_parenthesis(code: str, opening: int) -> int | None:
    depth = 0
    for offset in range(opening, len(code)):
        if code[offset] == "(":
            depth += 1
        elif code[offset] == ")":
            depth -= 1
            if depth == 0:
                return offset
    return None


def _is_declaration_like(code: str, call_start: int, opening: int) -> bool:
    line_start = code.rfind("\n", 0, call_start) + 1
    prefix = code[line_start:call_start].strip()
    if prefix.startswith("#"):
        return True
    closing = _matching_parenthesis(code, opening)
    if closing is not None:
        following = code[closing + 1 :]
        if re.match(r"\s*\{", following):
            return True
        if re.match(r"\s*\)\s*\([^;{}]*\)\s*[;{]", following):
            return True
    if not prefix:
        earlier_lines = code[:line_start].splitlines()
        prefix = next(
            (line.strip() for line in reversed(earlier_lines) if line.strip()),
            "",
        )
        if not prefix:
            return False
    first = prefix.split()[0]
    if first in {"return", "if", "while", "for", "switch", "case", "sizeof"}:
        return False
    return DECLARATION_PREFIX_RE.fullmatch(prefix) is not None


def loader_call_counts(text: str) -> dict[str, int]:
    code = C_NONCODE_RE.sub(_blank_noncode, text)
    counts: dict[str, int] = {}
    for match in LOADER_CALL_RE.finditer(code):
        if _is_declaration_like(code, match.start(), match.end() - 1):
            continue
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def dynamic_reference_counts(text: str) -> dict[str, int]:
    """Count resolver-family code references, including declarations and tables.

    Comments, character literals, and string literals are blanked.  Unlike the
    call scanner, this intentionally retains declarations, definitions, macro
    uses, and function-pointer table entries so a newly introduced wrapper or
    resolver alias cannot sit outside the exact source inventory.
    """

    code = C_NONCODE_RE.sub(_blank_noncode, text)
    counts: dict[str, int] = {}
    for name in DYNAMIC_IDENTIFIER_FAMILY_RE.findall(code):
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def scan_dynamic_references(
    root: Path, roots: Sequence[str], suffixes: Sequence[str]
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    suffix_set = set(suffixes)
    for relative_root in roots:
        base = root / relative_root
        require(base.is_dir(), f"dynamic-reference scan root absent: {relative_root}")
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            if path.suffix not in suffix_set:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError) as exc:
                raise AuditFailure(f"cannot scan dynamic references in {path}: {exc}") from exc
            counts = dynamic_reference_counts(text)
            if counts:
                result[path.relative_to(root).as_posix()] = counts
    return result


def scan_loader_calls(
    root: Path, roots: Sequence[str], suffixes: Sequence[str]
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
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
            counts = loader_call_counts(text)
            if counts:
                result[path.relative_to(root).as_posix()] = counts
    return result


def validate_loader_inventory(
    actual: Mapping[str, Mapping[str, int]], expected: Mapping[str, Mapping[str, int]]
) -> None:
    normalized_actual = {
        path: dict(sorted(counts.items())) for path, counts in sorted(actual.items())
    }
    normalized_expected = {
        path: dict(sorted(counts.items())) for path, counts in sorted(expected.items())
    }
    require(
        normalized_actual == normalized_expected,
        f"loader call/path inventory differs: {normalized_actual}",
    )


def validate_dynamic_reference_inventory(
    actual: Mapping[str, Mapping[str, int]], expected: Mapping[str, Mapping[str, int]]
) -> None:
    normalized_actual = {
        path: dict(sorted(counts.items())) for path, counts in sorted(actual.items())
    }
    normalized_expected = {
        path: dict(sorted(counts.items())) for path, counts in sorted(expected.items())
    }
    require(
        normalized_actual == normalized_expected,
        f"dynamic reference/path inventory differs: {normalized_actual}",
    )


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


def validate_tool_observation(
    observation: Mapping[str, Any],
    release_manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    check_files: bool = True,
) -> dict[str, Any]:
    require_exact_keys(
        observation,
        [
            "schema",
            "kind",
            "source_prepared_only",
            "build_attempted",
            "openocd_executed",
            "build_allowed",
            "package_versions",
            "file_identities",
            "blocking_mismatches",
        ],
        "tool observation",
    )
    require(observation["schema"] == 1, "tool observation schema must be 1")
    require(
        observation["kind"] == "R6_LIVE_BOUNDARY_READ_ONLY_TOOL_OBSERVATION",
        "tool observation kind differs",
    )
    require(observation["source_prepared_only"] is True, "tool observation is not source-only")
    require(observation["build_attempted"] is False, "tool observation claims a build")
    require(observation["openocd_executed"] is False, "tool observation claims OpenOCD execution")
    require(observation["build_allowed"] is False, "tool observation permits a build")

    platform = policy["platform"]
    environment = release_manifest["build_environment"][platform]
    expected_packages = environment["packages"]
    package_records = observation["package_versions"]
    require_exact_keys(package_records, expected_packages, "tool-observation package records")
    reference_packages = set(environment.get("reference_packages", []))
    derived_mismatches: list[str] = []
    for package, expected_version in expected_packages.items():
        record = package_records[package]
        require_exact_keys(record, ["expected", "observed", "status"], f"package {package}")
        require(record["expected"] == expected_version, f"package expected version differs: {package}")
        require(
            isinstance(record["observed"], str) and bool(record["observed"]),
            f"package observed version invalid: {package}",
        )
        if record["observed"] == expected_version:
            expected_status = "REFERENCE_MATCH" if package in reference_packages else "MATCH"
        else:
            expected_status = "MISMATCH_BUILD_BLOCKED"
            derived_mismatches.append(package)
        require(record["status"] == expected_status, f"package status differs: {package}")

    expected_mismatches = policy["expected_blocking_mismatches"]
    require(expected_mismatches == sorted(expected_mismatches), "policy mismatch set must be sorted")
    require(len(expected_mismatches) == len(set(expected_mismatches)), "policy mismatch set has duplicates")
    require(sorted(derived_mismatches) == expected_mismatches, "derived package mismatch set differs")
    require(observation["blocking_mismatches"] == expected_mismatches, "recorded mismatch set differs")

    identities = observation["file_identities"]
    required_paths = policy["required_identity_paths"]
    require(len(required_paths) == len(set(required_paths)), "identity path policy has duplicates")
    require_exact_keys(identities, required_paths, "tool-observation file identities")
    checked: dict[str, dict[str, Any]] = {}
    for raw_path in required_paths:
        record = identities[raw_path]
        require_exact_keys(record, ["size", "sha256"], f"file identity {raw_path}")
        require(
            isinstance(record["size"], int)
            and not isinstance(record["size"], bool)
            and record["size"] > 0,
            f"file identity size invalid: {raw_path}",
        )
        require(
            isinstance(record["sha256"], str)
            and HEX64_RE.fullmatch(record["sha256"]) is not None,
            f"file identity SHA-256 invalid: {raw_path}",
        )
        path = Path(raw_path)
        require(path.is_absolute(), f"file identity path is not absolute: {raw_path}")
        if check_files:
            require(path.is_file(), f"observed tool file absent: {raw_path}")
            actual_size = path.stat().st_size
            actual_hash = sha256_file(path)
            require(actual_size == record["size"], f"observed tool size differs: {raw_path}")
            require(actual_hash == record["sha256"], f"observed tool SHA-256 differs: {raw_path}")
            checked[raw_path] = {"size": actual_size, "sha256": actual_hash}
    return {
        "packages": len(package_records),
        "blocking_mismatches": expected_mismatches,
        "checked_file_identities": checked,
    }


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


def validate_tracked_fixture_inventory(
    source: Path,
    tracked_files: Sequence[str],
    artifact_policy: Mapping[str, Any],
    fixture_manifest: Mapping[str, Any],
    expected_tree: str,
) -> list[str]:
    require_exact_keys(
        fixture_manifest,
        ["schema", "kind", "source_tree", "artifacts"],
        "tracked fixture manifest",
    )
    require(fixture_manifest["schema"] == 1, "tracked fixture manifest schema must be 1")
    require(
        fixture_manifest["kind"] == "R6_OPENOCD_TRACKED_FIXTURE_ARTIFACTS",
        "tracked fixture manifest kind differs",
    )
    require(fixture_manifest["source_tree"] == expected_tree, "tracked fixture source tree differs")
    fixture_hashes = fixture_manifest["artifacts"]
    require(isinstance(fixture_hashes, Mapping), "tracked fixture artifacts must be an object")
    declared_paths = artifact_policy["tracked_fixture_artifacts"]
    require(len(declared_paths) == len(set(declared_paths)), "tracked fixture allowlist has duplicates")
    require_exact_keys(fixture_hashes, declared_paths, "tracked fixture hash records")
    require(set(declared_paths).issubset(tracked_files), "tracked fixture allowlist contains untracked paths")
    tracked_artifact_names = sorted(
        path
        for path in tracked_files
        if _matches_artifact_name(
            Path(path).name,
            artifact_policy["file_suffixes"],
            artifact_policy["file_name_regexes"],
        )
    )
    require(
        tracked_artifact_names == sorted(declared_paths),
        f"tracked fixture artifact inventory differs: {tracked_artifact_names}",
    )
    for relative in declared_paths:
        expected_hash = fixture_hashes[relative]
        require(
            isinstance(expected_hash, str) and HEX64_RE.fullmatch(expected_hash) is not None,
            f"tracked fixture hash invalid: {relative}",
        )
        fixture_path = source / relative
        require(fixture_path.is_file(), f"tracked fixture absent: {relative}")
        require(sha256_file(fixture_path) == expected_hash, f"tracked fixture SHA-256 differs: {relative}")
    return sorted(declared_paths)


def _verify_source_identity(
    source: Path, manifest: Mapping[str, Any], repo_root: Path
) -> dict[str, Any]:
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
    source_inventory = manifest["source_inventory"]
    artifact_policy = source_inventory["artifact_policy"]
    fixture_manifest_relative = artifact_policy["fixture_manifest_path"]
    require(
        fixture_manifest_relative in manifest["deterministic_inputs"],
        "tracked fixture manifest is not hash-bound",
    )
    fixture_manifest = load_json_strict(repo_root / fixture_manifest_relative)
    tracked_fixtures = validate_tracked_fixture_inventory(
        source,
        files,
        artifact_policy,
        fixture_manifest,
        expected["tree"],
    )
    rule_inventory_relative = artifact_policy["rule_inventory_path"]
    require(
        rule_inventory_relative in manifest["deterministic_inputs"],
        "artifact rule inventory is not hash-bound",
    )
    rule_inventory = load_json_strict(repo_root / rule_inventory_relative)
    artifact_rules = validate_artifact_rule_inventory(
        source,
        artifact_policy,
        rule_inventory,
        expected["tree"],
    )
    filesystem_artifacts = scan_build_artifacts(
        source,
        artifact_policy["file_suffixes"],
        artifact_policy["file_name_regexes"],
        artifact_policy["directory_names"],
        artifact_policy["directory_prefixes"],
        tracked_fixtures,
        artifact_policy["exact_file_paths"],
    )
    require(
        filesystem_artifacts == {"files": [], "directories": []},
        f"source-tree build artifacts present: {filesystem_artifacts}",
    )

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
        "tracked_fixture_artifacts": tracked_fixtures,
        "build_artifacts": filesystem_artifacts,
        "artifact_rules": artifact_rules,
    }


def run_audit(source: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    source = source.resolve()
    repo_root = repo_root.resolve()
    require(source.is_dir(), f"source directory absent: {source}")
    manifest = load_json_strict(repo_root / "tools/openocd/r6_live_boundary/phase0_manifest.json")
    observation = load_json_strict(repo_root / "tools/openocd/r6_live_boundary/tool_observation.json")
    release_manifest = load_json_strict(repo_root / "tools/openocd/manifest.json")

    require(manifest["schema"] == 1, "Phase-0 manifest schema must be 1")
    require(manifest["status"] == "SOURCE_INVENTORY_ONLY_COMPILE_REFUSED", "unexpected Phase-0 state")
    for field in ("compile_authorized", "openocd_execution_authorized", "hardware_contact_authorized"):
        require(manifest[field] is False, f"{field} must remain false")
    require(manifest["blockers"], "Phase-0 must retain explicit blockers")

    for relative, expected_hash in manifest["deterministic_inputs"].items():
        verify_file_binding(repo_root / relative, expected_hash, relative)

    for policy_name in ("tool_observation_policy", "pe_import_policy"):
        schema_relative = manifest[policy_name]["schema_path"]
        require(
            schema_relative in manifest["deterministic_inputs"],
            f"unbound policy schema: {schema_relative}",
        )
        schema = load_json_strict(repo_root / schema_relative)
        require(
            schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
            f"unexpected JSON Schema dialect: {schema_relative}",
        )

    tool_observation = validate_tool_observation(
        observation,
        release_manifest,
        manifest["tool_observation_policy"],
    )

    source_identity = _verify_source_identity(source, manifest, repo_root)
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
        object_plan["source_tree_build_artifacts_expected"] == {"files": [], "directories": []},
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
    declared_loader_names = loader["direct_api_names"] + loader["indirect_api_names"]
    require(
        len(declared_loader_names) == len(set(declared_loader_names)),
        "loader identifier inventory has duplicates",
    )
    require(
        set(declared_loader_names) == set(LOADER_IDENTIFIERS),
        "loader identifier inventory differs from scanner",
    )
    require(
        loader["identifier_family_pattern"] == DYNAMIC_IDENTIFIER_FAMILY_PATTERN,
        "dynamic identifier family pattern differs from scanner",
    )
    references = scan_dynamic_references(
        source, loader["roots"], loader["source_suffixes"]
    )
    validate_dynamic_reference_inventory(
        references, loader["expected_reference_inventory"]
    )
    discovered_identifiers = sorted(
        {name for counts in references.values() for name in counts}
    )
    require(
        discovered_identifiers == loader["expected_discovered_identifiers"],
        f"dynamic identifier inventory differs: {discovered_identifiers}",
    )
    calls = scan_loader_calls(source, loader["roots"], loader["source_suffixes"])
    expected_calls = {
        path: disposition["calls"]
        for path, disposition in loader["expected_path_dispositions"].items()
    }
    validate_loader_inventory(calls, expected_calls)
    literals = scan_forbidden_literals(
        source,
        loader["roots"],
        loader["source_suffixes"],
        loader["forbidden_dll_literals"],
    )
    require(not literals, f"forbidden DLL literals found: {literals}")
    for relative in source_inventory["planned_adapter_sources"]:
        text = (source / relative).read_text(encoding="utf-8", errors="strict")
        require(not loader_call_counts(text), f"loader API in planned source: {relative}")
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
        "dynamic_references": references,
        "forbidden_literals": literals,
        "backend_inventory": {
            "selected_real_implementations": backend_inventory["selected_real_implementations"],
            "excluded_real_implementations": backend_inventory["excluded_real_implementations"],
            "final_object_membership_frozen": False,
        },
        "object_inventory": {
            "phase0_compiled_objects": [],
            "source_tree_build_artifacts": source_identity["build_artifacts"],
            "tracked_fixture_artifact_count": len(source_identity["tracked_fixture_artifacts"]),
            "final_object_inventory_frozen": False,
        },
        "tool_observation": tool_observation,
        "compile_authorized": False,
        "openocd_execution_authorized": False,
        "hardware_contact_authorized": False,
        "blocking_package_mismatches": tool_observation["blocking_mismatches"],
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
