#!/usr/bin/env python3
"""Prepare and statically audit the R6 Phase1B deny-only Windows build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Iterable, Mapping

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from tools.openocd.r6_live_boundary import phase1a


MANIFEST_PATH = HERE / "phase1b_manifest.json"
PHASE1A_MANIFEST_PATH = HERE / "phase1a_manifest.json"
ACCEPTED_PHASE1A = "5b03850c0197a861be170a4c82aac9e8b1bfc5b4"
PROVENANCE_NAME = "PHASE1B-PREPARED.json"
EXPECTED_MANIFEST_SEMANTIC_SHA256 = (
    "05b8d03d450c8da67a4fd4865b6406afa3c8375cfb35eb77c347dd236d152735"
)
EXPECTED_CHANGED_PATHS = {
    "tools/openocd/r6_live_boundary/PHASE1B.md",
    "tools/openocd/r6_live_boundary/phase1b.py",
    "tools/openocd/r6_live_boundary/phase1b_build.sh",
    "tools/openocd/r6_live_boundary/phase1b_manifest.json",
    "tools/openocd/r6_live_boundary/test_phase1b.py",
}


class Phase1BFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase1BFailure(message)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise Phase1BFailure(f"cannot read strict JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def exact_keys(value: Mapping, expected: set[str], label: str) -> None:
    require(isinstance(value, Mapping), f"{label} is not an object")
    actual = set(value)
    require(
        actual == expected,
        f"{label} keys differ: missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise Phase1BFailure(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def verify_file(path: Path, record: Mapping, label: str) -> None:
    exact_keys(record, {"size", "sha256"}, f"{label} identity")
    require(path.is_file(), f"{label} is missing: {path}")
    require(path.stat().st_size == record["size"], f"{label} size differs")
    require(sha256(path) == record["sha256"], f"{label} SHA-256 differs")


def run(argv: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        stderr = getattr(exc, "stderr", "")
        raise Phase1BFailure(f"command failed: {' '.join(argv)}: {stderr}") from exc
    return result.stdout


def git(repo: Path, *args: str) -> str:
    return run(["git", "-C", str(repo), *args]).strip()


def inventory(root: Path) -> dict:
    require(root.is_dir(), f"inventory root is missing: {root}")
    records: list[str] = []
    total_size = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        item_stat = os.lstat(path)
        attributes = getattr(item_stat, "st_file_attributes", 0)
        require(
            not (attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)),
            f"inventory contains a reparse point: {relative}",
        )
        require(not stat.S_ISLNK(item_stat.st_mode), f"inventory contains a symlink: {relative}")
        if stat.S_ISDIR(item_stat.st_mode):
            continue
        require(stat.S_ISREG(item_stat.st_mode), f"inventory contains a foreign type: {relative}")
        digest = sha256(path)
        total_size += item_stat.st_size
        records.append(f"{relative}\0{item_stat.st_size}\0{digest}\n")
    encoded = "".join(records).encode("utf-8")
    return {
        "file_count": len(records),
        "total_size": total_size,
        "records_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    refused = {".git", "AGAMEMNON-PROVENANCE.json", "AGAMEMNON-PATCHES"}
    return set(names) & refused


def _apply_patch(root: Path, patch: Path, *, directory: str | None = None) -> None:
    command = ["git", "-C", str(root), "apply", "--whitespace=error-all"]
    if directory is not None:
        command.append(f"--directory={directory}")
    command.append(str(patch))
    run(command)
    reverse = ["git", "-C", str(root), "apply", "--check", "--reverse"]
    if directory is not None:
        reverse.append(f"--directory={directory}")
    reverse.append(str(patch))
    run(reverse)


def validate_manifest(manifest: dict) -> None:
    exact_keys(
        manifest,
        {
            "schema", "kind", "status", "parent_agamemnon_commit",
            "compile_authorized", "openocd_execution_authorized",
            "hardware_contact_authorized", "source_date_epoch", "tool_identities",
            "prepared_source", "build_contract", "artifact_evidence", "remaining_gates",
        },
        "Phase1B manifest",
    )
    require(manifest["schema"] == 1, "Phase1B schema differs")
    require(
        manifest["kind"] == "AGAMEMNON_R6_OPENOCD_LIVE_BOUNDARY_PHASE1B",
        "Phase1B kind differs",
    )
    require(
        manifest["status"] == "DETERMINISTIC_MINIMAL_BUILD_STATIC_AUDIT_CANDIDATE",
        "Phase1B status differs",
    )
    require(manifest["parent_agamemnon_commit"] == ACCEPTED_PHASE1A,
            "Phase1B accepted parent differs")
    require(manifest["compile_authorized"] is True, "Phase1B compilation is not authorized")
    require(manifest["openocd_execution_authorized"] is False,
            "OpenOCD execution must remain refused")
    require(manifest["hardware_contact_authorized"] is False,
            "hardware contact must remain refused")
    require(manifest["source_date_epoch"] == 1777198205, "source date epoch differs")

    tools = manifest["tool_identities"]
    require(set(tools) == {"ar", "nm", "objdump", "strings"}, "static tool set differs")
    for name, record in tools.items():
        exact_keys(record, {"path", "size", "sha256"}, f"{name} tool")
        require(record["path"].startswith("C:/msys64/ucrt64/bin/"),
                f"{name} tool escaped UCRT64")

    prepared = manifest["prepared_source"]
    exact_keys(prepared, {"openocd", "libusb", "postpatch_files"}, "prepared source")
    exact_keys(prepared["openocd"], {"commit", "tree", "inventory"}, "prepared OpenOCD")
    exact_keys(prepared["libusb"], {"archive_size", "archive_sha256", "inventory"},
               "prepared libusb")
    require(len(prepared["postpatch_files"]) == 6, "postpatch file set differs")
    for relative, record in prepared["postpatch_files"].items():
        require(relative.startswith(("openocd-source/", "libusb-source/")),
                f"postpatch file escaped source roots: {relative}")
        exact_keys(record, {"size", "sha256"}, f"postpatch {relative}")

    contract = manifest["build_contract"]
    exact_keys(
        contract,
        {
            "enabled_adapter_macros", "configure_flags", "cflags", "ldflags",
            "libusb_link_flags", "required_objects", "forbidden_objects",
            "jim_required_configure_token", "jim_forbidden_undefined_symbols",
            "private_string_markers",
        },
        "build contract",
    )
    require(contract["enabled_adapter_macros"] == ["BUILD_CMSIS_DAP_USB"],
            "enabled adapter macro set differs")
    require(contract["jim_required_configure_token"] == "--without-ext=load",
            "Jim load extension is not refused")
    require("windows_usbdk.o" in contract["forbidden_objects"],
            "UsbDk object is not forbidden")

    evidence = manifest["artifact_evidence"]
    exact_keys(
        evidence,
        {
            "openocd_pe", "libusb_archive", "libopenocd_archive", "libjim_archive",
            "object_inventory", "normalized_configure_sha256", "normalized_link_sha256",
            "jim_win32compat_undefined_symbols", "adjacent_bin_files", "direct_imports",
            "delay_imports", "main_instructions", "private_string_matches",
        },
        "artifact evidence",
    )
    require(evidence["adjacent_bin_files"] == ["openocd.exe"],
            "adjacent binary policy differs")
    require(evidence["delay_imports"] == [], "delay imports must be empty")
    require(evidence["jim_win32compat_undefined_symbols"] == [],
            "Jim win32 compatibility retained loader imports")
    require(evidence["private_string_matches"] == [], "private string matches are preclaimed")
    require(manifest["remaining_gates"], "remaining gate list is empty")
    semantic = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    require(semantic == EXPECTED_MANIFEST_SEMANTIC_SHA256,
            "Phase1B manifest semantic identity differs")


def validate_candidate(repo: Path, parent: str) -> None:
    ancestry = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    require(len(ancestry) == 2, "Phase1B candidate must have one parent")
    require(ancestry[1] == parent, "Phase1B candidate is not an exact child of Phase1A")
    changed = set(filter(None, git(repo, "diff", "--name-only", parent, "HEAD").splitlines()))
    require(changed == EXPECTED_CHANGED_PATHS,
            f"Phase1B candidate path inventory differs: {sorted(changed)}")
    require(git(repo, "status", "--porcelain=v1", "--untracked-files=all") == "",
            "Phase1B candidate worktree is not clean")


def validate_tools(manifest: dict) -> None:
    observation = phase1a.load_json_strict(HERE / "tool_observation.json")
    for name, record in manifest["tool_identities"].items():
        path = Path(record["path"])
        verify_file(path, {"size": record["size"], "sha256": record["sha256"]}, name)
        if name in {"nm", "objdump", "strings"}:
            require(observation["file_identities"][record["path"]] == {
                "size": record["size"], "sha256": record["sha256"]
            }, f"{name} differs from the accepted observation")


def validate_pristine_inputs(source: Path, libusb_archive: Path, libusb_source: Path,
                             package_cache: Path) -> None:
    prior = phase1a.load_json_strict(PHASE1A_MANIFEST_PATH)
    phase1a.validate_manifest(prior)
    phase1a.validate_toolchain(REPOSITORY, prior, package_cache)
    phase1a.validate_openocd(REPOSITORY, prior, source)
    phase1a.validate_libusb(REPOSITORY, prior, libusb_archive, libusb_source)


def prepare(source: Path, libusb_archive: Path, libusb_source: Path, output: Path,
            package_cache: Path) -> None:
    manifest = load_json_strict(MANIFEST_PATH)
    validate_manifest(manifest)
    validate_tools(manifest)
    validate_pristine_inputs(source, libusb_archive, libusb_source, package_cache)
    require(not output.exists(), f"prepared output already exists: {output}")
    output.mkdir(parents=True)
    openocd_output = output / "openocd-source"
    libusb_output = output / "libusb-source"
    try:
        shutil.copytree(source, openocd_output, ignore=_copy_ignore, symlinks=True)
        shutil.copytree(libusb_source, libusb_output, ignore=_copy_ignore, symlinks=True)
        phase1a_manifest = phase1a.load_json_strict(PHASE1A_MANIFEST_PATH)
        _apply_patch(
            openocd_output,
            REPOSITORY / phase1a_manifest["openocd_source"]["patch"],
        )
        _apply_patch(
            openocd_output,
            REPOSITORY / phase1a_manifest["jimtcl"]["patch"],
            directory="jimtcl",
        )
        _apply_patch(
            libusb_output,
            REPOSITORY / phase1a_manifest["libusb"]["patch"],
        )
        provenance = {
            "schema": 1,
            "kind": "AGAMEMNON_R6_PHASE1B_PREPARED_SOURCE",
            "openocd_commit": phase1a_manifest["openocd_source"]["commit"],
            "openocd_tree": phase1a_manifest["openocd_source"]["tree"],
            "libusb_archive_size": libusb_archive.stat().st_size,
            "libusb_archive_sha256": sha256(libusb_archive),
            "patch_sha256": {
                "openocd": phase1a_manifest["openocd_source"]["patch_sha256"],
                "jimtcl": phase1a_manifest["jimtcl"]["patch_sha256"],
                "libusb": phase1a_manifest["libusb"]["patch_sha256"],
            },
            "openocd_inventory": inventory(openocd_output),
            "libusb_inventory": inventory(libusb_output),
        }
        raw = json.dumps(provenance, indent=2, ensure_ascii=False) + "\n"
        (output / PROVENANCE_NAME).write_text(raw, encoding="utf-8", newline="\n")
        validate_prepared(output, manifest)
    except Exception:
        # The caller supplied a fresh private root. Preserve a failed tree for diagnosis.
        raise
    print("PASS_PHASE1B_PREPARED_SOURCE")


def validate_prepared(prepared_root: Path, manifest: dict) -> None:
    provenance = load_json_strict(prepared_root / PROVENANCE_NAME)
    exact_keys(
        provenance,
        {
            "schema", "kind", "openocd_commit", "openocd_tree",
            "libusb_archive_size", "libusb_archive_sha256", "patch_sha256",
            "openocd_inventory", "libusb_inventory",
        },
        "Phase1B prepared provenance",
    )
    require(provenance["schema"] == 1, "prepared provenance schema differs")
    require(provenance["kind"] == "AGAMEMNON_R6_PHASE1B_PREPARED_SOURCE",
            "prepared provenance kind differs")
    expected = manifest["prepared_source"]
    require(provenance["openocd_commit"] == expected["openocd"]["commit"],
            "prepared OpenOCD commit differs")
    require(provenance["openocd_tree"] == expected["openocd"]["tree"],
            "prepared OpenOCD tree differs")
    require(provenance["libusb_archive_size"] == expected["libusb"]["archive_size"],
            "prepared libusb archive size differs")
    require(provenance["libusb_archive_sha256"] == expected["libusb"]["archive_sha256"],
            "prepared libusb archive hash differs")
    prior = phase1a.load_json_strict(PHASE1A_MANIFEST_PATH)
    require(provenance["patch_sha256"] == {
        "openocd": prior["openocd_source"]["patch_sha256"],
        "jimtcl": prior["jimtcl"]["patch_sha256"],
        "libusb": prior["libusb"]["patch_sha256"],
    }, "prepared patch identity differs")
    actual_openocd = inventory(prepared_root / "openocd-source")
    actual_libusb = inventory(prepared_root / "libusb-source")
    require(provenance["openocd_inventory"] == actual_openocd,
            "prepared OpenOCD provenance inventory differs")
    require(provenance["libusb_inventory"] == actual_libusb,
            "prepared libusb provenance inventory differs")
    require(actual_openocd == expected["openocd"]["inventory"],
            "prepared OpenOCD manifest inventory differs")
    require(actual_libusb == expected["libusb"]["inventory"],
            "prepared libusb manifest inventory differs")
    for relative, identity in expected["postpatch_files"].items():
        verify_file(prepared_root / relative, identity, f"prepared {relative}")


def _tool(manifest: dict, name: str, *args: str) -> str:
    path = manifest["tool_identities"][name]["path"]
    return run([path, *args])


def archive_members(manifest: dict, path: Path) -> list[str]:
    return [line for line in _tool(manifest, "ar", "t", str(path)).splitlines() if line]


def _records_digest(records: Iterable[str]) -> str:
    return hashlib.sha256("".join(f"{record}\n" for record in records).encode("utf-8")).hexdigest()


def object_inventory(root: Path) -> dict:
    records = []
    for path in sorted(root.rglob("*.o"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        records.append(f"{relative}\0{path.stat().st_size}\0{sha256(path)}")
    return {"count": len(records), "records_sha256": _records_digest(records)}


def normalize_build_paths(text: str, build_root: Path) -> str:
    native = str(build_root.resolve())
    forward = native.replace("\\", "/")
    variants = {
        native,
        forward,
        forward[0].lower() + forward[1:] if forward else forward,
        f"/{forward[0].lower()}{forward[2:]}" if re.match(r"^[A-Za-z]:/", forward) else forward,
    }
    result = text
    for variant in sorted(variants, key=len, reverse=True):
        result = result.replace(variant, "@BUILD_ROOT@")
    return result


def _configure_invocation(build_root: Path) -> str:
    log = (build_root / "openocd-build/config.log").read_text(encoding="utf-8")
    for line in log.splitlines():
        if line.startswith("  $ ") and "/configure " in line:
            return normalize_build_paths(line[4:], build_root)
    raise Phase1BFailure("OpenOCD configure invocation is missing")


def _link_invocation(build_root: Path) -> str:
    log = (build_root / "openocd-build.log").read_text(encoding="utf-8")
    matches = [
        line for line in log.splitlines()
        if line.startswith("libtool: link: x86_64-w64-mingw32-gcc ")
        and " -o src/openocd.exe " in line
    ]
    require(len(matches) == 1, "final OpenOCD linker invocation is not unique")
    return normalize_build_paths(matches[0], build_root)


def _pe_imports(manifest: dict, executable: Path) -> tuple[list[str], list[str]]:
    output = _tool(manifest, "objdump", "-p", str(executable))
    direct = sorted({
        match.group(1).lower()
        for match in re.finditer(r"^\s*DLL Name:\s*(\S+)\s*$", output, re.MULTILINE)
    })
    delay = re.search(
        r"^Entry d\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+Delay Import Directory$",
        output,
        re.MULTILINE,
    )
    require(delay is not None, "PE delay-import directory is missing")
    delay_imports = [] if int(delay.group(1), 16) == 0 and int(delay.group(2), 16) == 0 else ["present"]
    return direct, delay_imports


def _main_instructions(manifest: dict, executable: Path) -> list[str]:
    output = _tool(manifest, "objdump", "-d", str(executable))
    match = re.search(r"^[0-9a-f]+ <main>:\n(?P<body>(?:\s+[0-9a-f]+:.*\n)+)", output, re.MULTILINE)
    require(match is not None, "final main disassembly is missing")
    instructions = []
    for line in match.group("body").splitlines():
        item = re.match(r"\s*[0-9a-f]+:\s+(?:[0-9a-f]{2}\s+)+\s*(.*)$", line)
        if item:
            normalized = re.sub(r"\b[0-9a-f]+ <(__main)>$", r"<\1>", item.group(1))
            instructions.append(normalized)
    return instructions


def _private_matches(manifest: dict, executable: Path) -> list[str]:
    strings = _tool(manifest, "strings", "-a", str(executable)).splitlines()
    markers = [item.lower() for item in manifest["build_contract"]["private_string_markers"]]
    return sorted({line for line in strings if any(marker in line.lower() for marker in markers)})


def validate_build(build_root: Path, manifest: dict) -> None:
    evidence = manifest["artifact_evidence"]
    contract = manifest["build_contract"]
    executable = build_root / "openocd-stage/opt/agamemnon-openocd/bin/openocd.exe"
    libusb = build_root / "libusb-stage/opt/agamemnon-libusb/lib/libusb-1.0.a"
    libopenocd = build_root / "openocd-build/src/.libs/libopenocd.a"
    libjim = build_root / "openocd-build/jimtcl/libjim.a"
    for path, record, label in (
        (executable, evidence["openocd_pe"], "OpenOCD PE"),
        (libusb, evidence["libusb_archive"], "libusb archive"),
        (libopenocd, evidence["libopenocd_archive"], "libopenocd archive"),
        (libjim, evidence["libjim_archive"], "libjim archive"),
    ):
        verify_file(path, {"size": record["size"], "sha256": record["sha256"]}, label)

    libusb_members = archive_members(manifest, libusb)
    require(libusb_members == evidence["libusb_archive"]["members"],
            "libusb archive membership differs")
    openocd_members = archive_members(manifest, libopenocd)
    require(len(openocd_members) == evidence["libopenocd_archive"]["member_count"],
            "libopenocd archive member count differs")
    require(_records_digest(openocd_members) == evidence["libopenocd_archive"]["members_sha256"],
            "libopenocd archive membership differs")
    jim_members = archive_members(manifest, libjim)
    require(len(jim_members) == evidence["libjim_archive"]["member_count"],
            "libjim archive member count differs")
    require(_records_digest(jim_members) == evidence["libjim_archive"]["members_sha256"],
            "libjim archive membership differs")

    actual_objects = object_inventory(build_root)
    require(actual_objects == evidence["object_inventory"], "compiled object inventory differs")
    object_names = [path.name for path in build_root.rglob("*.o")]
    for required in contract["required_objects"]:
        require(required in object_names, f"required object is missing: {required}")
    for forbidden in contract["forbidden_objects"]:
        require(forbidden not in object_names, f"forbidden object is present: {forbidden}")
        require(forbidden not in libusb_members + openocd_members + jim_members,
                f"forbidden archive member is present: {forbidden}")

    config_h = (build_root / "openocd-build/config.h").read_text(encoding="utf-8")
    enabled = sorted(re.findall(r"^#define (BUILD_\S+) 1$", config_h, re.MULTILINE))
    require(enabled == contract["enabled_adapter_macros"], "configured adapter set differs")
    jim_config = (build_root / "openocd-build/jimtcl/config.log").read_text(encoding="utf-8")
    require(contract["jim_required_configure_token"] in jim_config,
            "Jim load extension refusal is missing")

    configure = _configure_invocation(build_root)
    for flag in contract["configure_flags"]:
        require(flag in configure.split(), f"configure flag is missing: {flag}")
    require(hashlib.sha256(configure.encode("utf-8")).hexdigest()
            == evidence["normalized_configure_sha256"], "configure invocation differs")
    link = _link_invocation(build_root)
    for token in contract["libusb_link_flags"]:
        require(token in link.split(), f"link input is missing: {token}")
    require(hashlib.sha256(link.encode("utf-8")).hexdigest()
            == evidence["normalized_link_sha256"], "link invocation differs")

    jim_object = build_root / "openocd-build/jimtcl/jim-win32compat.o"
    require(jim_object.is_file(), "jim-win32compat.o is missing")
    undefined = sorted(filter(None, (
        line.strip().split()[-1]
        for line in _tool(manifest, "nm", "-u", str(jim_object)).splitlines()
        if line.strip()
    )))
    require(undefined == evidence["jim_win32compat_undefined_symbols"],
            "Jim win32 compatibility undefined symbols differ")
    for forbidden in contract["jim_forbidden_undefined_symbols"]:
        require(forbidden not in undefined, f"Jim loader symbol is present: {forbidden}")

    adjacent = sorted(path.name for path in (
        build_root / "openocd-stage/opt/agamemnon-openocd/bin"
    ).iterdir()
                      if path.is_file())
    require(adjacent == evidence["adjacent_bin_files"], "adjacent binary inventory differs")
    direct, delay = _pe_imports(manifest, executable)
    require(direct == evidence["direct_imports"], "PE direct imports differ")
    require(delay == evidence["delay_imports"], "PE delay imports differ")
    instructions = _main_instructions(manifest, executable)
    require(instructions == evidence["main_instructions"], "deny-gate disassembly differs")
    require(any("$0x46,%eax" in item for item in instructions), "deny exit code is absent")
    require(not any(token in " ".join(instructions) for token in ("setvbuf", "openocd_main")),
            "denied main retained a post-gate call")
    require(_private_matches(manifest, executable) == evidence["private_string_matches"],
            "private path or vendor marker leaked into the PE")


def audit(prepared_root: Path, build_root: Path, package_cache: Path) -> None:
    manifest = load_json_strict(MANIFEST_PATH)
    validate_manifest(manifest)
    validate_candidate(REPOSITORY, manifest["parent_agamemnon_commit"])
    validate_tools(manifest)
    prior = phase1a.load_json_strict(PHASE1A_MANIFEST_PATH)
    phase1a.validate_manifest(prior)
    phase1a.validate_toolchain(REPOSITORY, prior, package_cache)
    validate_prepared(prepared_root, manifest)
    validate_build(build_root, manifest)
    print("PASS_PHASE1B_DETERMINISTIC_MINIMAL_BUILD_STATIC_ONLY_OPENOCD_NOT_EXECUTED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--source", required=True, type=Path)
    prepare_parser.add_argument("--libusb-archive", required=True, type=Path)
    prepare_parser.add_argument("--libusb-source", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify-prepared")
    verify_parser.add_argument("--prepared-root", required=True, type=Path)
    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--prepared-root", required=True, type=Path)
    audit_parser.add_argument("--build-root", required=True, type=Path)
    for item in (prepare_parser, audit_parser):
        item.add_argument(
            "--package-cache", type=Path, default=Path("C:/msys64/var/cache/pacman/pkg")
        )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "prepare":
            prepare(args.source.resolve(), args.libusb_archive.resolve(),
                    args.libusb_source.resolve(), args.output.resolve(),
                    args.package_cache.resolve())
        elif args.command == "verify-prepared":
            manifest = load_json_strict(MANIFEST_PATH)
            validate_manifest(manifest)
            validate_tools(manifest)
            validate_prepared(args.prepared_root.resolve(), manifest)
            print("PASS_PHASE1B_PREPARED_SOURCE_VERIFIED")
        else:
            audit(args.prepared_root.resolve(), args.build_root.resolve(),
                  args.package_cache.resolve())
    except (Phase1BFailure, phase1a.Phase1AFailure) as exc:
        raise SystemExit(f"R6 Phase1B audit failed: {exc}") from exc


if __name__ == "__main__":
    main()
