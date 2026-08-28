#!/usr/bin/env python3
"""Prepare, audit, and control the desk-only R6 Phase1C launch boundary."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any, Callable, Iterator, Mapping

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from tools.openocd.r6_live_boundary import phase1b


MANIFEST_PATH = HERE / "phase1c_manifest.json"
PATCH_PATH = HERE / "phase1c_patches/0001-openocd-one-shot-launch-gate.patch"
WINUSB_PATCH_PATH = HERE / "phase1c_patches/0002-libusb-direct-winusb-imports.patch"
AUTHORIZATION_TEMPLATE_PATH = HERE / "phase1c_authorization.template.json"
AUTHORIZATION_GENESIS_PATH = HERE / "phase1c_authorization.genesis.json"
ACCEPTED_PHASE1B = "70c24a5b575bacd0c11af7c1edb26fc1c602194d"
PROVENANCE_NAME = "PHASE1C-PREPARED.json"
READY_MAGIC = b"R6GATE1\n"
CONTINUE_TOKEN = b"R6GO"
DENIED_EXIT = 70
MAX_AUTHORIZATION_SECONDS = 900


class Phase1CFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase1CFailure(message)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"),
                           object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise Phase1CFailure(f"cannot read strict JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def exact_keys(value: Mapping, expected: set[str], label: str) -> None:
    require(isinstance(value, Mapping), f"{label} is not an object")
    actual = set(value)
    require(actual == expected,
            f"{label} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}")


def canonical_bytes(value: Mapping) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")


def semantic_sha256(value: Mapping) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise Phase1CFailure(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def verify_file(path: Path, identity: Mapping, label: str) -> None:
    exact_keys(identity, {"size", "sha256"}, f"{label} identity")
    require(path.is_file(), f"{label} is missing: {path}")
    require(path.stat().st_size == identity["size"], f"{label} size differs")
    require(sha256(path) == identity["sha256"], f"{label} SHA-256 differs")


def _ordinary_directory(path: Path, label: str) -> None:
    try:
        item = os.lstat(path)
    except OSError as exc:
        raise Phase1CFailure(f"cannot stat {label}: {exc}") from exc
    require(stat.S_ISDIR(item.st_mode), f"{label} is not a directory")
    require(not stat.S_ISLNK(item.st_mode), f"{label} is a symlink")
    attributes = getattr(item, "st_file_attributes", 0)
    require(not attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            f"{label} is a reparse point")


def _portable_absolute(value: str, label: str) -> Path:
    require(isinstance(value, str) and value and "\x00" not in value,
            f"{label} path is malformed")
    require("\\" not in value, f"{label} path is not canonical forward-slash form")
    path = Path(value)
    require(path.is_absolute(), f"{label} path is not absolute")
    require(path.as_posix() == value, f"{label} path is not canonical")
    return path


def _parse_utc(value: Any, label: str) -> dt.datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} is not UTC")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Phase1CFailure(f"{label} is malformed") from exc
    require(parsed.tzinfo == dt.timezone.utc, f"{label} is not exact UTC")
    require(parsed.microsecond == 0, f"{label} has fractional seconds")
    return parsed


def validate_manifest(manifest: dict) -> None:
    exact_keys(manifest, {
        "schema", "kind", "status", "parent_agamemnon_commit", "package_id",
        "compile_authorized", "openocd_execution_authorized",
        "hardware_contact_authorized", "authorization_epoch", "gate_protocol",
        "retained_phase1b", "prepared_source", "controller_source", "artifact_evidence",
        "live_readiness_contract", "remaining_gates",
    }, "Phase1C manifest")
    require(manifest["schema"] == 1, "Phase1C schema differs")
    require(manifest["kind"] == "AGAMEMNON_R6_OPENOCD_LIVE_BOUNDARY_PHASE1C",
            "Phase1C kind differs")
    require(manifest["status"] == "DESK_ONLY_ONE_SHOT_LAUNCH_CANDIDATE",
            "Phase1C status differs")
    require(manifest["parent_agamemnon_commit"] == ACCEPTED_PHASE1B,
            "Phase1C parent differs")
    require(manifest["compile_authorized"] is True, "compilation is not retained")
    require(manifest["openocd_execution_authorized"] is False,
            "OpenOCD execution must remain refused")
    require(manifest["hardware_contact_authorized"] is False,
            "hardware contact must remain refused")
    require(re.fullmatch(r"[A-Z0-9_-]{16,96}", manifest["package_id"]) is not None,
            "package id is malformed")
    require(re.fullmatch(r"[A-Z0-9_-]{16,96}", manifest["authorization_epoch"])
            is not None, "authorization epoch is malformed")

    protocol = manifest["gate_protocol"]
    exact_keys(protocol, {
        "denied_exit", "ready_magic_hex", "continue_token_hex", "nonce_hex_length",
        "private_argument_prefixes", "minimum_post_strip_argc", "default_denied",
        "private_arguments_stripped", "report_precedes_continue",
    }, "gate protocol")
    require(protocol == {
        "denied_exit": DENIED_EXIT,
        "ready_magic_hex": READY_MAGIC.hex(),
        "continue_token_hex": CONTINUE_TOKEN.hex(),
        "nonce_hex_length": 64,
        "private_argument_prefixes": [
            "--r6-gate-read-handle=", "--r6-gate-write-handle=",
            "--r6-gate-nonce="],
        "minimum_post_strip_argc": 2,
        "default_denied": True,
        "private_arguments_stripped": True,
        "report_precedes_continue": True,
    }, "gate protocol differs")

    retained = manifest["retained_phase1b"]
    exact_keys(retained, {"manifest_semantic_sha256",
                          "build_contract_semantic_sha256",
                          "prepared_source_semantic_sha256"}, "retained Phase1B")
    prior = phase1b.load_json_strict(phase1b.MANIFEST_PATH)
    phase1b.validate_manifest(prior)
    require(retained["manifest_semantic_sha256"] == semantic_sha256(prior),
            "retained Phase1B manifest differs")
    require(retained["build_contract_semantic_sha256"] ==
            semantic_sha256(prior["build_contract"]),
            "retained Phase1B build contract differs")
    require(retained["prepared_source_semantic_sha256"] ==
            semantic_sha256(prior["prepared_source"]),
            "retained Phase1B source contract differs")

    prepared = manifest["prepared_source"]
    exact_keys(prepared, {"phase1b_inventory", "phase1c_inventory", "patches",
                          "postpatch_main", "postpatch_libusb"}, "prepared source")
    require(set(prepared["patches"]) == {"gate", "direct_winusb"},
            "Phase1C patch set differs")
    expected_patches = {"gate": PATCH_PATH, "direct_winusb": WINUSB_PATCH_PATH}
    for name, path in expected_patches.items():
        exact_keys(prepared["patches"][name], {"path", "size", "sha256"},
                   f"{name} patch")
        require(prepared["patches"][name]["path"] ==
                path.relative_to(REPOSITORY).as_posix(), f"{name} patch path differs")
        verify_file(path, {key: prepared["patches"][name][key]
                           for key in ("size", "sha256")}, f"{name} patch")
    exact_keys(prepared["phase1b_inventory"],
               {"file_count", "total_size", "records_sha256"},
               "phase1b_inventory")
    exact_keys(prepared["phase1c_inventory"],
               {"openocd-source", "libusb-source"}, "phase1c_inventory")
    for label, value in prepared["phase1c_inventory"].items():
        exact_keys(value, {"file_count", "total_size", "records_sha256"}, label)
    exact_keys(prepared["postpatch_main"], {"size", "sha256"}, "postpatch main")
    require(set(prepared["postpatch_libusb"]) == {
        "libusb/os/windows_common.c", "libusb/os/windows_common.h",
        "libusb/os/windows_winusb.c"
    }, "postpatch libusb source set differs")
    for name, identity in prepared["postpatch_libusb"].items():
        exact_keys(identity, {"size", "sha256"}, f"postpatch {name}")

    controller = manifest["controller_source"]
    require(set(controller) == {
        "phase1a.py", "phase1b.py", "phase1c.py", "phase1c_win32.py",
        "phase1c_build.sh", "phase1c_authorization.template.json",
        "phase1c_authorization.genesis.json",
    },
            "controller source set differs")
    for name, identity in controller.items():
        verify_file(HERE / name, identity, f"controller {name}")

    evidence = manifest["artifact_evidence"]
    exact_keys(evidence, {
        "openocd_pe", "libusb_archive", "libopenocd_archive", "libjim_archive",
        "object_inventory", "normalized_configure_sha256", "normalized_link_sha256",
        "jim_win32compat_undefined_symbols", "adjacent_bin_files", "direct_imports",
        "direct_import_symbols", "delay_imports", "main_instructions_sha256", "main_calls",
        "gate_instructions_sha256", "gate_calls",
        "fixed_system_resolver_callers", "fixed_system_resolver_instructions_sha256",
        "fixed_system_resolver_calls", "fixed_system_resolver_target_strings",
        "private_string_matches", "forbidden_loader_matches",
        "libusb_loader_undefined_symbols",
    }, "artifact evidence")
    require(evidence["adjacent_bin_files"] == ["openocd.exe"],
            "adjacent binary set differs")
    require(evidence["delay_imports"] == [], "delay imports are present")
    require(evidence["jim_win32compat_undefined_symbols"] == [],
            "Jim loader imports are present")
    require(evidence["private_string_matches"] == [], "private strings are present")
    require(evidence["forbidden_loader_matches"] == [],
            "generic/optional loader surface is present")
    require(evidence["libusb_loader_undefined_symbols"] == [],
            "libusb loader imports are present")
    for library in ("winusb.dll", "cfgmgr32.dll", "advapi32.dll",
                    "setupapi.dll", "hid.dll"):
        require(library in evidence["direct_imports"],
                f"system library is not a direct import: {library}")
    require(set(evidence["direct_import_symbols"]) == set(evidence["direct_imports"]),
            "direct import DLL/symbol inventory differs")
    require(all(isinstance(symbols, list) and symbols
                for symbols in evidence["direct_import_symbols"].values()),
            "direct import symbol inventory is incomplete")
    require("GetProcAddress" in evidence["direct_import_symbols"]["kernel32.dll"],
            "fixed MinGW resolver import is missing")
    require(evidence["main_calls"] == ["__main", "r6_live_boundary_gate",
                                        "setvbuf", "setvbuf", "openocd_main"],
            "main call order differs")
    require(evidence["gate_calls"] == [
        "r6_parse_handle", "r6_parse_handle", "__imp_CloseHandle",
        "__imp_CloseHandle", "__imp_WriteFile", "__imp_ReadFile",
    ], "gate call set or order differs")
    require(evidence["fixed_system_resolver_callers"] == ["getntptimeofday"],
            "fixed system resolver caller differs")
    require(evidence["fixed_system_resolver_calls"] == [
        "__imp_GetTimeZoneInformation", "__imp_GetModuleHandleA",
        "__imp_GetProcAddress",
    ], "fixed system resolver call order differs")
    require(evidence["fixed_system_resolver_target_strings"] == [
        "GetSystemTimePreciseAsFileTime"
    ], "fixed system resolver target differs")

    readiness = manifest["live_readiness_contract"]
    exact_keys(readiness, {
        "required_independent_accepts", "maximum_authorization_seconds",
        "maximum_uses", "exact_launch_argv_grammar", "receipt_before_create_process",
        "create_suspended", "assign_job_before_resume", "exact_handle_list",
        "module_attestation_complete", "api_set_attestation_complete",
    }, "live readiness contract")
    require(readiness == {
        "required_independent_accepts": 2,
        "maximum_authorization_seconds": MAX_AUTHORIZATION_SECONDS,
        "maximum_uses": 1,
        "exact_launch_argv_grammar": ["-s", "SCRIPTS", "-f", "CONFIG", "-f", "COMMAND"],
        "receipt_before_create_process": True,
        "create_suspended": True,
        "assign_job_before_resume": True,
        "exact_handle_list": ["gate-read", "gate-write", "stdin-null", "combined-log"],
        "module_attestation_complete": False,
        "api_set_attestation_complete": False,
    }, "live readiness contract differs")
    require(manifest["remaining_gates"] == [
        "INDEPENDENT_PHASE1C_LIVE_READINESS_AUDIT_1_NOT_COMPLETE",
        "INDEPENDENT_PHASE1C_LIVE_READINESS_AUDIT_2_NOT_COMPLETE",
        "MODULE_API_SET_AND_MITIGATION_ATTESTATION_NOT_COMPLETE",
        "FRESH_ONE_SHOT_BOARD_GO_NOT_PRESENT",
        "EXECUTABLE_SCRIPT_CONFIG_AND_LOG_NAMESPACE_CUSTODY_NOT_COMPLETE",
        "AUTHORIZATION_INPUT_AND_STATE_NAMESPACE_CUSTODY_NOT_COMPLETE",
        "EXTERNAL_GO_PROVENANCE_AUTHENTICATION_NOT_COMPLETE",
        "OPENOCD_EXECUTION_NOT_AUTHORIZED",
        "HARDWARE_CONTACT_NOT_AUTHORIZED",
    ], "remaining gates differ")


def _identity_record(path: Path) -> dict:
    return {"size": path.stat().st_size, "sha256": sha256(path)}


def validate_launch_request(request: dict, manifest: dict) -> dict:
    exact_keys(request, {
        "schema", "kind", "package_id", "authorization_epoch", "session_id",
        "session_number", "nonce", "openocd", "scripts", "config", "command",
        "argv", "argv_sha256",
    }, "launch request")
    require(request["schema"] == 1 and
            request["kind"] == "AGAMEMNON_R6_PHASE1C_EXACT_LAUNCH_REQUEST",
            "launch request identity differs")
    require(request["package_id"] == manifest["package_id"], "wrong package request")
    require(request["authorization_epoch"] == manifest["authorization_epoch"],
            "wrong authorization epoch")
    require(isinstance(request["session_id"], str) and
            re.fullmatch(r"[a-z0-9][a-z0-9-]{15,95}", request["session_id"]),
            "session id is malformed")
    require(type(request["session_number"]) is int and request["session_number"] > 0,
            "session number is malformed")
    require(isinstance(request["nonce"], str) and
            re.fullmatch(r"[0-9a-f]{64}", request["nonce"]), "nonce is malformed")
    verify_file(_portable_absolute(request["openocd"]["path"], "OpenOCD"),
                {k: request["openocd"][k] for k in ("size", "sha256")}, "OpenOCD")
    exact_keys(request["openocd"], {"path", "size", "sha256"}, "OpenOCD record")
    require({k: request["openocd"][k] for k in ("size", "sha256")} ==
            manifest["artifact_evidence"]["openocd_pe"], "wrong OpenOCD package")

    exact_keys(request["scripts"], {"path", "inventory"}, "scripts record")
    scripts = _portable_absolute(request["scripts"]["path"], "scripts")
    _ordinary_directory(scripts, "scripts")
    require(phase1b.inventory(scripts) == request["scripts"]["inventory"],
            "scripts inventory differs")
    for label in ("config", "command"):
        exact_keys(request[label], {"path", "size", "sha256"}, f"{label} record")
        verify_file(_portable_absolute(request[label]["path"], label),
                    {k: request[label][k] for k in ("size", "sha256")}, label)
    expected_argv = [
        "-s", request["scripts"]["path"], "-f", request["config"]["path"],
        "-f", request["command"]["path"],
    ]
    require(request["argv"] == expected_argv, "wrong command or config argv")
    require(all(isinstance(item, str) and item and "\x00" not in item
                for item in request["argv"]), "argv is malformed")
    argv_raw = json.dumps(request["argv"], separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    require(request["argv_sha256"] == hashlib.sha256(argv_raw).hexdigest(),
            "argv digest differs")
    return request


def _validate_audit(path: Path, identity: Mapping, manifest: dict,
                    auditor_ids: set[str]) -> None:
    verify_file(path, identity, "live-readiness audit")
    audit = load_json_strict(path)
    exact_keys(audit, {
        "schema", "kind", "auditor_id", "verdict", "desk_only",
        "package_id", "manifest_semantic_sha256",
        "openocd", "openocd_executed", "hardware_contacted",
    }, "live-readiness audit")
    require(audit["schema"] == 1 and
            audit["kind"] == "AGAMEMNON_R6_PHASE1C_LIVE_READINESS_AUDIT",
            "audit identity differs")
    require(audit["verdict"] == "ACCEPT" and audit["desk_only"] is True,
            "audit is not a desk-only ACCEPT")
    require(audit["openocd_executed"] is False and
            audit["hardware_contacted"] is False, "audit crossed the live boundary")
    require(audit["package_id"] == manifest["package_id"], "audit package differs")
    require(audit["manifest_semantic_sha256"] == semantic_sha256(manifest),
            "audit manifest differs")
    require(audit["openocd"] == manifest["artifact_evidence"]["openocd_pe"],
            "audit PE differs")
    require(isinstance(audit["auditor_id"], str) and audit["auditor_id"] and
            audit["auditor_id"] not in auditor_ids, "auditors are not independent")
    auditor_ids.add(audit["auditor_id"])


def validate_authorization(go: dict, request_path: Path, request: dict,
                           manifest: dict, now: dt.datetime) -> None:
    exact_keys(go, {
        "schema", "kind", "authorization_state", "package_id",
        "authorization_epoch", "session_id", "session_number", "nonce",
        "issued_utc", "expires_utc", "maximum_uses", "board_contact_authorized",
        "launch_request", "live_readiness_audits",
    }, "authorization")
    require(go["schema"] == 1 and
            go["kind"] == "AGAMEMNON_R6_PHASE1C_ONE_SHOT_AUTHORIZATION",
            "authorization identity differs")
    require(go["authorization_state"] == "LIVE_AUTHORIZED",
            "authorization is not live")
    require(go["package_id"] == manifest["package_id"], "wrong package authority")
    require(go["authorization_epoch"] == manifest["authorization_epoch"],
            "wrong authorization epoch")
    for field in ("session_id", "session_number", "nonce"):
        require(go[field] == request[field], f"authorization {field} differs")
    issued = _parse_utc(go["issued_utc"], "issued_utc")
    expires = _parse_utc(go["expires_utc"], "expires_utc")
    require(now.tzinfo == dt.timezone.utc, "validation time is not UTC")
    require(issued <= now <= expires, "authorization is not currently valid")
    require(dt.timedelta(0) < expires - issued <= dt.timedelta(
        seconds=MAX_AUTHORIZATION_SECONDS), "authorization lifetime differs")
    require(go["maximum_uses"] == 1, "authorization is not one-shot")
    require(go["board_contact_authorized"] is True,
            "authorization does not permit board contact")
    exact_keys(go["launch_request"], {"path", "size", "sha256"},
               "authorized launch request")
    require(Path(go["launch_request"]["path"]).as_posix() == request_path.as_posix(),
            "authorized request path differs")
    verify_file(request_path, {k: go["launch_request"][k]
                               for k in ("size", "sha256")}, "launch request")
    audits = go["live_readiness_audits"]
    require(isinstance(audits, list) and len(audits) == 2,
            "exactly two audits are required")
    auditor_ids: set[str] = set()
    for record in audits:
        exact_keys(record, {"path", "size", "sha256"}, "audit authority record")
        _validate_audit(_portable_absolute(record["path"], "audit"),
                        {k: record[k] for k in ("size", "sha256")},
                        manifest, auditor_ids)


def _receipt_name(session_number: int, nonce: str) -> str:
    return f"receipt-{session_number:020d}-{nonce}.json"


def _load_receipts(receipts: Path, epoch: str) -> list[dict]:
    _ordinary_directory(receipts, "receipts directory")
    result = []
    for path in sorted(receipts.iterdir(), key=lambda item: item.name):
        require(re.fullmatch(r"receipt-[0-9]{20}-[0-9a-f]{64}\.json", path.name)
                is not None, f"foreign receipt entry: {path.name}")
        value = load_json_strict(path)
        exact_keys(value, {"schema", "kind", "authorization_epoch", "session_id",
                           "session_number", "nonce", "go_sha256", "request_sha256",
                           "consumed_utc", "state"}, "receipt")
        require(value["schema"] == 1 and value["kind"] ==
                "AGAMEMNON_R6_PHASE1C_AUTHORIZATION_RECEIPT", "receipt identity differs")
        require(value["authorization_epoch"] == epoch, "receipt epoch differs")
        require(value["state"] == "CONSUMED", "receipt is not terminal")
        require(path.name == _receipt_name(value["session_number"], value["nonce"]),
                "receipt pathname differs")
        result.append(value)
    return result


@contextlib.contextmanager
def authorization_lock(state_dir: Path) -> Iterator[None]:
    lock_path = state_dir / "consumer.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise Phase1CFailure("authorization consumer is already locked") from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise Phase1CFailure("authorization consumer is already locked") from exc
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _durable_exclusive(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_SYNC", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            require(written > 0, "receipt write made no progress")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_write_through(source: Path, destination: Path) -> None:
    if os.name == "nt":
        import ctypes
        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
        move.restype = ctypes.c_int
        if not move(str(source), str(destination), 0x1 | 0x8):
            raise Phase1CFailure(
                f"write-through high-water replace failed: {ctypes.get_last_error()}")
    else:
        os.replace(source, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def consume_authorization(go_path: Path, go: dict, request_path: Path,
                          state_dir: Path, now: dt.datetime) -> Path:
    _ordinary_directory(state_dir, "authorization state")
    allowed = {"high-water.json", "receipts", "consumer.lock"}
    foreign = {item.name for item in state_dir.iterdir()} - allowed
    require(not foreign, f"foreign authorization state entries: {sorted(foreign)}")
    high_path = state_dir / "high-water.json"
    high = load_json_strict(high_path)
    exact_keys(high, {"schema", "kind", "authorization_epoch", "last_session_number"},
               "high-water")
    require(high["schema"] == 1 and high["kind"] ==
            "AGAMEMNON_R6_PHASE1C_AUTHORIZATION_HIGH_WATER", "high-water identity differs")
    require(high["authorization_epoch"] == go["authorization_epoch"],
            "high-water epoch differs")
    receipts_dir = state_dir / "receipts"
    receipts = _load_receipts(receipts_dir, go["authorization_epoch"])
    observed = max([high["last_session_number"]] +
                   [item["session_number"] for item in receipts])
    require(go["session_number"] > observed, "authorization is replayed or out of order")
    receipt_path = receipts_dir / _receipt_name(go["session_number"], go["nonce"])
    require(not receipt_path.exists(), "authorization receipt already exists")
    receipt = {
        "schema": 1,
        "kind": "AGAMEMNON_R6_PHASE1C_AUTHORIZATION_RECEIPT",
        "authorization_epoch": go["authorization_epoch"],
        "session_id": go["session_id"],
        "session_number": go["session_number"],
        "nonce": go["nonce"],
        "go_sha256": sha256(go_path),
        "request_sha256": sha256(request_path),
        "consumed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": "CONSUMED",
    }
    _durable_exclusive(receipt_path, canonical_bytes(receipt))
    reread = load_json_strict(receipt_path)
    require(reread == receipt, "durable receipt reread differs")
    next_high = dict(high)
    next_high["last_session_number"] = go["session_number"]
    temp = state_dir / f"high-water.{go['nonce']}.tmp"
    try:
        _durable_exclusive(temp, canonical_bytes(next_high))
        _replace_write_through(temp, high_path)
    except BaseException:
        # The receipt is already terminal. A high-water failure burns authority.
        raise
    require(load_json_strict(high_path) == next_high, "high-water reread differs")
    return receipt_path


def _launch_authorized_core(manifest: dict, go_path: Path, request_path: Path,
                            state_dir: Path, log_path: Path,
                            backend: Callable[..., int],
                            now: dt.datetime | None = None) -> int:
    request = load_json_strict(request_path)
    validate_launch_request(request, manifest)
    go_sha256 = sha256(go_path)
    go = load_json_strict(go_path)
    require(sha256(go_path) == go_sha256, "authorization changed while opening")
    current = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    validate_authorization(go, request_path, request, manifest, current)
    require(not log_path.exists(), "launch log already exists")
    _ordinary_directory(log_path.parent, "launch log parent")
    with authorization_lock(state_dir):
        receipt = consume_authorization(go_path, go, request_path, state_dir, current)
        # Burn first, then repeat every pathname/content check at the final pre-create edge.
        validate_launch_request(request, manifest)
        require(sha256(request_path) == go["launch_request"]["sha256"],
                "launch request changed after authorization consumption")
        require(sha256(go_path) == go_sha256,
                "authorization changed after consumption")
        require(semantic_sha256(load_json_strict(MANIFEST_PATH)) ==
                semantic_sha256(manifest), "Phase1C manifest changed after consumption")
        for name, identity in manifest["controller_source"].items():
            verify_file(HERE / name, identity, f"controller {name}")
        # This call is deliberately after the terminal receipt and high-water reread.
        return backend(
            executable=_portable_absolute(request["openocd"]["path"], "OpenOCD"),
            argv=list(request["argv"]), nonce=request["nonce"], log_path=log_path,
            cwd=_portable_absolute(request["openocd"]["path"], "OpenOCD").parent,
            receipt_path=receipt,
        )


def launch_authorized(go_path: Path, request_path: Path, state_dir: Path,
                      log_path: Path, backend: Callable[..., int],
                      now: dt.datetime | None = None) -> int:
    """Public policy edge; the desk-only Phase1C manifest always refuses live use."""
    manifest = load_json_strict(MANIFEST_PATH)
    validate_manifest(manifest)
    require(manifest["openocd_execution_authorized"] is True,
            "Phase1C manifest does not authorize OpenOCD execution")
    require(manifest["hardware_contact_authorized"] is True,
            "Phase1C manifest does not authorize hardware contact")
    return _launch_authorized_core(
        manifest, go_path.resolve(), request_path.resolve(), state_dir.resolve(),
        log_path.resolve(), backend, now)


def _launch_authorized_desk_test_only(go_path: Path, request_path: Path,
                                      state_dir: Path, log_path: Path,
                                      backend: Callable[..., int],
                                      now: dt.datetime | None = None) -> int:
    """Private seam for fault-scheduling the future consumer without live authority."""
    manifest = load_json_strict(MANIFEST_PATH)
    validate_manifest(manifest)
    require(manifest["openocd_execution_authorized"] is False and
            manifest["hardware_contact_authorized"] is False,
            "desk-only launch model received live authority")
    return _launch_authorized_core(
        manifest, go_path, request_path, state_dir, log_path, backend, now)


def validate_authorization_template() -> None:
    template = load_json_strict(AUTHORIZATION_TEMPLATE_PATH)
    require(template.get("authorization_state") == "TEMPLATE_NOT_AUTHORIZED",
            "authorization template is not inert")
    require(template.get("maximum_uses") == 0, "authorization template has uses")
    require(template.get("board_contact_authorized") is False,
            "authorization template permits contact")
    require(template.get("live_readiness_audits") == [],
            "authorization template contains audits")


def validate_prepared(prepared_root: Path, manifest: dict) -> None:
    provenance = load_json_strict(prepared_root / PROVENANCE_NAME)
    exact_keys(provenance, {"schema", "kind", "phase1b_inventory", "patch_sha256",
                            "phase1c_inventory"}, "prepared provenance")
    require(provenance["schema"] == 1 and provenance["kind"] ==
            "AGAMEMNON_R6_PHASE1C_PREPARED_SOURCE", "prepared identity differs")
    expected = manifest["prepared_source"]
    require(provenance["phase1b_inventory"] == expected["phase1b_inventory"],
            "Phase1B input inventory differs")
    require(provenance["patch_sha256"] == {
        name: record["sha256"] for name, record in expected["patches"].items()
    }, "Phase1C patch identities differ")
    actual = phase1b.inventory(prepared_root)
    # The provenance file is included in the final inventory; compare the two source roots instead.
    roots = {
        "openocd-source": phase1b.inventory(prepared_root / "openocd-source"),
        "libusb-source": phase1b.inventory(prepared_root / "libusb-source"),
    }
    require(provenance["phase1c_inventory"] == roots,
            "prepared source inventories differ")
    require(expected["phase1c_inventory"] == roots,
            "prepared manifest inventories differ")
    verify_file(prepared_root / "openocd-source/src/main.c",
                expected["postpatch_main"], "postpatch main")
    for name, identity in expected["postpatch_libusb"].items():
        path = prepared_root / "libusb-source" / name
        verify_file(path, identity, f"postpatch {name}")
        lowered = path.read_text(encoding="utf-8").lower()
        require(not any(token in lowered for token in (
            "loadlibrary", "getprocaddress", "freelibrary", "load_system_library"
        )), f"postpatch source retains a generic loader: {name}")
    del actual


def prepare(phase1b_root: Path, output: Path) -> None:
    manifest = load_json_strict(MANIFEST_PATH)
    validate_manifest(manifest)
    prior = phase1b.load_json_strict(phase1b.MANIFEST_PATH)
    phase1b.validate_prepared(phase1b_root, prior)
    require(not output.exists(), f"prepared output already exists: {output}")
    output.mkdir(parents=True)
    shutil.copytree(phase1b_root / "openocd-source", output / "openocd-source")
    shutil.copytree(phase1b_root / "libusb-source", output / "libusb-source")
    phase1b._apply_patch(output / "openocd-source", PATCH_PATH)
    phase1b._apply_patch(output / "libusb-source", WINUSB_PATCH_PATH)
    roots = {
        "openocd-source": phase1b.inventory(output / "openocd-source"),
        "libusb-source": phase1b.inventory(output / "libusb-source"),
    }
    provenance = {
        "schema": 1, "kind": "AGAMEMNON_R6_PHASE1C_PREPARED_SOURCE",
        "phase1b_inventory": phase1b.inventory(phase1b_root),
        "patch_sha256": {"gate": sha256(PATCH_PATH),
                          "direct_winusb": sha256(WINUSB_PATCH_PATH)},
        "phase1c_inventory": roots,
    }
    (output / PROVENANCE_NAME).write_bytes(canonical_bytes(provenance))
    validate_prepared(output, manifest)
    print("PASS_PHASE1C_PREPARED_SOURCE")


def _symbol_instructions(manifest: dict, executable: Path, symbol: str) -> list[str]:
    output = phase1b._tool(manifest, "objdump", "-d", str(executable))
    match = re.search(
        rf"^[0-9a-f]+ <{re.escape(symbol)}>:\n(?P<body>(?:\s+[0-9a-f]+:.*\n)+)",
        output,
        re.MULTILINE,
    )
    require(match is not None, f"final {symbol} disassembly is missing")
    instructions = []
    for line in match.group("body").splitlines():
        item = re.match(r"\s*[0-9a-f]+:\s+(?:[0-9a-f]{2}\s+)+\s*(.*)$", line)
        if item:
            instructions.append(item.group(1))
    return instructions


def _called_symbols(instructions: list[str]) -> list[str]:
    calls = []
    for item in instructions:
        if not item.startswith("call"):
            continue
        targets = re.findall(r"<([^>]+)>", item)
        if not targets:
            continue
        target = re.sub(r"\.(?:constprop|isra)\.\d+$", "", targets[-1])
        calls.append(target)
    return calls


def _pe_import_symbol_inventory(manifest: dict, executable: Path) -> dict[str, list[str]]:
    output = phase1b._tool(manifest, "objdump", "-p", str(executable))
    result: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        dll = re.match(r"^\s*DLL Name:\s*(\S+)\s*$", line)
        if dll:
            current = dll.group(1).lower()
            require(current not in result, f"duplicate PE import library: {current}")
            result[current] = []
            continue
        symbol = re.match(
            r"^\s*[0-9a-fA-F]+\s+<none>\s+[0-9a-fA-F]+\s+(\S+)\s*$", line)
        if current is not None and symbol:
            result[current].append(symbol.group(1))
    for dll, symbols in result.items():
        require(symbols, f"PE import library has no symbols: {dll}")
    return {dll: sorted(symbols) for dll, symbols in sorted(result.items())}


def _import_callers(manifest: dict, executable: Path, imported: str) -> list[str]:
    output = phase1b._tool(manifest, "objdump", "-d", str(executable))
    current = None
    callers = []
    target = f"<__imp_{imported}>"
    for line in output.splitlines():
        header = re.match(r"^[0-9a-f]+ <([^>]+)>:$", line)
        if header:
            current = header.group(1)
        elif current and "call" in line and target in line:
            callers.append(current)
    return sorted(set(callers))


def validate_build(build_root: Path, manifest: dict) -> None:
    prior = phase1b.load_json_strict(phase1b.MANIFEST_PATH)
    retained = prior["build_contract"]
    evidence = manifest["artifact_evidence"]
    executable = build_root / "openocd-stage/opt/agamemnon-openocd/bin/openocd.exe"
    for label, path, record in (
        ("OpenOCD PE", executable, evidence["openocd_pe"]),
        ("libusb archive", build_root / "libusb-stage/opt/agamemnon-libusb/lib/libusb-1.0.a",
         evidence["libusb_archive"]),
        ("libopenocd archive", build_root / "openocd-build/src/.libs/libopenocd.a",
         evidence["libopenocd_archive"]),
        ("libjim archive", build_root / "openocd-build/jimtcl/libjim.a",
         evidence["libjim_archive"]),
    ):
        verify_file(path, {k: record[k] for k in ("size", "sha256")}, label)
    require(phase1b.object_inventory(build_root) == evidence["object_inventory"],
            "object inventory differs")
    object_names = [path.name for path in build_root.rglob("*.o")]
    for required in retained["required_objects"]:
        require(required in object_names, f"required object is missing: {required}")
    for forbidden in retained["forbidden_objects"]:
        require(forbidden not in object_names, f"forbidden object is present: {forbidden}")
    config_h = (build_root / "openocd-build/config.h").read_text(encoding="utf-8")
    enabled = sorted(re.findall(r"^#define (BUILD_\S+) 1$", config_h, re.MULTILINE))
    require(enabled == retained["enabled_adapter_macros"], "adapter set differs")
    configure = phase1b._configure_invocation(build_root)
    require(hashlib.sha256(configure.encode()).hexdigest() ==
            evidence["normalized_configure_sha256"], "configure invocation differs")
    link = phase1b._link_invocation(build_root)
    link_inputs = set(link.split())
    for required in ("-lwinusb", "-lcfgmgr32", "-ladvapi32", "-lsetupapi",
                     "-lhid"):
        require(required in link_inputs, f"direct system link input is missing: {required}")
    require(hashlib.sha256(link.encode()).hexdigest() ==
            evidence["normalized_link_sha256"], "link invocation differs")
    adjacent = sorted(path.name for path in executable.parent.iterdir() if path.is_file())
    require(adjacent == evidence["adjacent_bin_files"], "adjacent files differ")
    direct, delay = phase1b._pe_imports(prior, executable)
    require(direct == evidence["direct_imports"], "direct imports differ")
    require(delay == evidence["delay_imports"], "delay imports differ")
    require(_pe_import_symbol_inventory(prior, executable) ==
            evidence["direct_import_symbols"], "direct import symbols differ")
    forbidden_tokens = ("loadlibrary", "freelibrary",
                        "usbdk", "libusbk", "msys-usb", "\\%s.dll")
    string_output = phase1b._tool(prior, "strings", "-a", str(executable))
    loader_matches = sorted({line for line in string_output.splitlines()
                             if any(token in line.lower() for token in forbidden_tokens)})
    require(loader_matches == evidence["forbidden_loader_matches"],
            "PE loader/optional-backend string surface differs")
    loader_undefined = []
    for name in ("windows_common.o", "windows_winusb.o"):
        path = build_root / "libusb-build/libusb/os" / name
        require(path.is_file(), f"libusb object is missing: {name}")
        for line in phase1b._tool(prior, "nm", "-u", str(path)).splitlines():
            symbol = line.strip().split()[-1] if line.strip() else ""
            if any(token in symbol.lower() for token in
                   ("loadlibrary", "getprocaddress", "freelibrary")):
                loader_undefined.append(f"{name}:{symbol}")
    require(sorted(loader_undefined) == evidence["libusb_loader_undefined_symbols"],
            "libusb object loader imports differ")
    instructions = phase1b._main_instructions(prior, executable)
    require(hashlib.sha256("\n".join(instructions).encode()).hexdigest() ==
            evidence["main_instructions_sha256"], "main disassembly differs")
    calls = _called_symbols(instructions)
    require(calls == evidence["main_calls"], "main call order differs")
    require("r6_live_boundary_gate" in calls and calls.index("r6_live_boundary_gate") <
            calls.index("setvbuf") < calls.index("openocd_main"),
            "earliest gate ordering differs")
    gate_instructions = _symbol_instructions(prior, executable,
                                             "r6_live_boundary_gate")
    require(hashlib.sha256("\n".join(gate_instructions).encode()).hexdigest() ==
            evidence["gate_instructions_sha256"], "gate disassembly differs")
    require(_called_symbols(gate_instructions) == evidence["gate_calls"],
            "gate call order differs")
    resolver_instructions = _symbol_instructions(prior, executable,
                                                 "getntptimeofday")
    require(hashlib.sha256("\n".join(resolver_instructions).encode()).hexdigest() ==
            evidence["fixed_system_resolver_instructions_sha256"],
            "fixed system resolver disassembly differs")
    require(_called_symbols(resolver_instructions) ==
            evidence["fixed_system_resolver_calls"],
            "fixed system resolver calls differ")
    require(_import_callers(prior, executable, "GetProcAddress") ==
            evidence["fixed_system_resolver_callers"],
            "GetProcAddress escaped the fixed system resolver")
    target_strings = sorted(line for line in string_output.splitlines()
                            if line == "GetSystemTimePreciseAsFileTime")
    require(target_strings == evidence["fixed_system_resolver_target_strings"],
            "fixed system resolver target strings differ")
    strings = phase1b._private_matches(prior, executable)
    require(strings == evidence["private_string_matches"], "private strings differ")


def audit(prepared_root: Path, build_root: Path) -> None:
    manifest = load_json_strict(MANIFEST_PATH)
    validate_manifest(manifest)
    validate_authorization_template()
    validate_prepared(prepared_root, manifest)
    validate_build(build_root, manifest)
    print("PASS_PHASE1C_DESK_ONE_SHOT_BOUNDARY_OPENOCD_NOT_EXECUTED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--phase1b-prepared", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    verify_parser = sub.add_parser("verify-prepared")
    verify_parser.add_argument("--prepared-root", required=True, type=Path)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--prepared-root", required=True, type=Path)
    audit_parser.add_argument("--build-root", required=True, type=Path)
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--board-go", required=True, type=Path)
    launch_parser.add_argument("--request", required=True, type=Path)
    launch_parser.add_argument("--state-dir", required=True, type=Path)
    launch_parser.add_argument("--log", required=True, type=Path)
    return parser.parse_args()


def _win32_backend(**kwargs) -> int:
    """Import the live backend only after the public policy edge authorizes use."""
    from tools.openocd.r6_live_boundary.phase1c_win32 import launch_process
    return launch_process(**kwargs)


def main() -> None:
    args = parse_args()
    try:
        if args.command == "prepare":
            prepare(args.phase1b_prepared.resolve(), args.output.resolve())
        elif args.command == "verify-prepared":
            manifest = load_json_strict(MANIFEST_PATH)
            validate_manifest(manifest)
            validate_prepared(args.prepared_root.resolve(), manifest)
            print("PASS_PHASE1C_PREPARED_SOURCE_VERIFIED")
        elif args.command == "audit":
            audit(args.prepared_root.resolve(), args.build_root.resolve())
        else:
            return_code = launch_authorized(
                args.board_go, args.request, args.state_dir, args.log, _win32_backend)
            raise SystemExit(return_code)
    except (Phase1CFailure, phase1b.Phase1BFailure) as exc:
        raise SystemExit(f"R6 Phase1C failed: {exc}") from exc


if __name__ == "__main__":
    main()
