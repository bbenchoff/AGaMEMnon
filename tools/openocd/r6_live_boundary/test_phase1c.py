from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import pytest

from tools.openocd.r6_live_boundary import phase1c, phase1c_namespace


NOW = dt.datetime(2026, 8, 28, 12, 0, 0, tzinfo=dt.timezone.utc)


def manifest() -> dict:
    return phase1c.load_json_strict(phase1c.MANIFEST_PATH)


def identity(path: Path) -> dict:
    return {"size": path.stat().st_size, "sha256": phase1c.sha256(path)}


def write_json(path: Path, value: dict) -> None:
    path.write_bytes(phase1c.canonical_bytes(value))


def request_fixture(tmp_path: Path) -> tuple[dict, dict, Path]:
    value = manifest()
    executable = tmp_path / "openocd.exe"
    executable.write_bytes(b"desk-fixture-not-executable")
    value["artifact_evidence"]["openocd_pe"] = identity(executable)
    config = tmp_path / "agrv2k.cfg"
    config.write_bytes(phase1c.LIVE_CONFIG_PATH.read_bytes())
    command = tmp_path / "session.tcl"
    command.write_bytes(phase1c.LIVE_COMMAND_PATH.read_bytes())
    executable_path = phase1c_namespace.canonical_volume_path(executable)
    config_path = phase1c_namespace.canonical_volume_path(config)
    command_path = phase1c_namespace.canonical_volume_path(command)
    log_path = phase1c_namespace.canonical_volume_path(
        tmp_path / "launch.log", must_exist=False)
    argv = ["-f", config_path, "-f", command_path]
    request = {
        "schema": 1,
        "kind": "AGAMEMNON_R6_PHASE1C_EXACT_LAUNCH_REQUEST",
        "package_id": value["package_id"],
        "authorization_epoch": value["authorization_epoch"],
        "session_id": "phase1c-test-session-0001",
        "session_number": 1,
        "nonce": "12" * 32,
        "openocd": {"path": executable_path, **identity(executable)},
        "config": {"path": config_path, **identity(config)},
        "command": {"path": command_path, **identity(command)},
        "log": {"path": log_path},
        "argv": argv,
        "argv_sha256": hashlib.sha256(json.dumps(
            argv, separators=(",", ":")).encode()).hexdigest(),
    }
    request_path = tmp_path / "request.json"
    write_json(request_path, request)
    return value, request, request_path


def authorization_fixture(tmp_path: Path, value: dict, request: dict,
                          request_path: Path) -> tuple[dict, Path]:
    audits = []
    for index in range(2):
        audit = {
            "schema": 1,
            "kind": "AGAMEMNON_R6_PHASE1C_LIVE_READINESS_AUDIT",
            "auditor_id": f"independent-auditor-{index + 1}",
            "verdict": "ACCEPT",
            "desk_only": True,
            "package_id": value["package_id"],
            "manifest_semantic_sha256": phase1c.semantic_sha256(value),
            "openocd": value["artifact_evidence"]["openocd_pe"],
            "openocd_executed": False,
            "hardware_contacted": False,
        }
        path = tmp_path / f"audit-{index + 1}.json"
        write_json(path, audit)
        audits.append({"path": phase1c_namespace.canonical_volume_path(path),
                       **identity(path)})
    go = {
        "schema": 1,
        "kind": "AGAMEMNON_R6_PHASE1C_ONE_SHOT_AUTHORIZATION",
        "authorization_state": "LIVE_AUTHORIZED",
        "package_id": value["package_id"],
        "authorization_epoch": value["authorization_epoch"],
        "session_id": request["session_id"],
        "session_number": request["session_number"],
        "nonce": request["nonce"],
        "issued_utc": "2026-08-28T11:55:00Z",
        "expires_utc": "2026-08-28T12:05:00Z",
        "maximum_uses": 1,
        "board_contact_authorized": True,
        "launch_request": {"path": request_path.as_posix(), **identity(request_path)},
        "live_readiness_audits": audits,
    }
    path = tmp_path / "BOARD_GO_R6_PHASE1C.json"
    write_json(path, go)
    return go, path


def state_fixture(tmp_path: Path, epoch: str) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    (state / "receipts").mkdir()
    write_json(state / "high-water.json", {
        "schema": 1,
        "kind": "AGAMEMNON_R6_PHASE1C_AUTHORIZATION_HIGH_WATER",
        "authorization_epoch": epoch,
        "last_session_number": 0,
    })
    return state


def test_manifest_retains_phase1b_but_grants_no_live_authority() -> None:
    value = manifest()
    phase1c.validate_manifest(value)
    assert value["parent_agamemnon_commit"] == phase1c.ACCEPTED_PHASE1C
    assert value["compile_authorized"] is True
    assert value["openocd_execution_authorized"] is False
    assert value["hardware_contact_authorized"] is False
    assert "EXECUTABLE_SCRIPT_CONFIG_AND_LOG_NAMESPACE_CUSTODY_NOT_COMPLETE" not in (
        value["remaining_gates"])
    assert value["live_session_files"]["external_scripts_admitted"] is False
    assert {"phase1c_build.sh", "phase1c_authorization.template.json",
            "phase1c_authorization.genesis.json"} <= set(value["controller_source"])


def test_manifest_rejects_patch_identity_drift() -> None:
    value = manifest()
    value["prepared_source"]["patches"]["gate"]["sha256"] = "0" * 64
    with pytest.raises(phase1c.Phase1CFailure, match="gate patch SHA-256 differs"):
        phase1c.validate_manifest(value)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("openocd_execution_authorized", True),
     ("hardware_contact_authorized", True),
     ("parent_agamemnon_commit", "0" * 40)],
)
def test_manifest_rejects_authority_or_parent_drift(field: str, replacement) -> None:
    value = manifest()
    value[field] = replacement
    with pytest.raises(phase1c.Phase1CFailure):
        phase1c.validate_manifest(value)


def test_public_launch_refuses_inert_manifest_before_any_side_effect(tmp_path: Path) -> None:
    events = []

    def backend(**_kwargs):
        events.append("backend")
        return 0

    with pytest.raises(phase1c.Phase1CFailure, match="does not authorize OpenOCD"):
        phase1c.launch_authorized(
            tmp_path / "missing-go.json", tmp_path / "missing-request.json",
            tmp_path / "missing-state", tmp_path / "missing.log", backend, NOW)
    assert events == []
    assert list(tmp_path.iterdir()) == []


def test_public_cli_refuses_before_path_resolution_or_backend_import(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events = []
    monkeypatch.setattr(Path, "resolve", lambda self, *args, **kwargs:
                        events.append((self, args, kwargs)))
    monkeypatch.setattr(sys, "argv", [
        "phase1c.py", "launch", "--board-go", str(tmp_path / "missing-go.json"),
        "--request", str(tmp_path / "missing-request.json"),
        "--state-dir", str(tmp_path / "missing-state"),
        "--log", str(tmp_path / "missing.log"),
    ])
    with pytest.raises(SystemExit, match="does not authorize OpenOCD"):
        phase1c.main()
    assert events == []
    assert "tools.openocd.r6_live_boundary.phase1c_win32" not in sys.modules
    assert list(tmp_path.iterdir()) == []


def test_template_is_inert_and_genesis_is_zero() -> None:
    phase1c.validate_authorization_template()
    genesis = phase1c.load_json_strict(phase1c.AUTHORIZATION_GENESIS_PATH)
    assert genesis["last_session_number"] == 0
    assert genesis["authorization_epoch"] == manifest()["authorization_epoch"]


def test_gate_patch_has_default_deny_exact_protocol_and_argv_strip() -> None:
    source = phase1c.PATCH_PATH.read_text(encoding="utf-8")
    assert "R6_LIVE_BOUNDARY_DENIED = 70" in source
    assert "if (*argc < 5" in source
    assert "r6_write_exact(write_handle, report" in source
    assert "r6_read_exact(read_handle, command" in source
    assert "memcmp(command, r6_continue_token" in source
    assert "(*argv)[3] = (*argv)[0];" in source
    assert "*argv += 3;" in source and "*argc -= 3;" in source
    assert "desk override" not in source.lower()


def test_build_script_cannot_execute_openocd() -> None:
    source = phase1c.MANIFEST_PATH.with_name("phase1c_build.sh").read_text(
        encoding="utf-8")
    assert "PASS_PHASE1C_BUILD_COMPLETE_OPENOCD_NOT_EXECUTED" in source
    assert "openocd.exe --version" not in source
    assert '"$openocd_prefix/bin/openocd.exe"' not in source
    assert '"$python_script" verify-prepared' in source
    assert source.count("--enable-cmsis-dap-v2") == 1
    assert source.count("--disable-cmsis-dap") >= 1


def test_direct_winusb_patch_removes_generic_loader_and_build_links_system_import() -> None:
    patch = phase1c.WINUSB_PATCH_PATH.read_text(encoding="utf-8")
    build = phase1c.MANIFEST_PATH.with_name("phase1c_build.sh").read_text(
        encoding="utf-8")
    assert "-HMODULE load_system_library" in patch
    assert "-\thWinUSB = load_system_library" in patch
    for call in ("FreeLibrary(hWinUSB);", "FreeLibrary(hDll);"):
        lines = [line for line in patch.splitlines() if call in line]
        assert len(lines) == 1
        assert lines[0].startswith("-")
    added = [line for line in patch.splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    assert not any(token in line for line in added for token in
                   ("LoadLibrary", "GetProcAddress", "FreeLibrary",
                    "load_system_library"))
    assert '__asm__("__imp_" DLL_STRINGIFY(name))' in patch
    assert "+#define WinUSB_Bind(fn)" in patch
    for library in ("-lwinusb", "-lcfgmgr32", "-ladvapi32", "-lsetupapi",
                    "-lhid"):
        assert library in build


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda request, value: request.__setitem__("package_id", "WRONG_PACKAGE_000"),
         "wrong package"),
        (lambda request, value: request["argv"].__setitem__(1, request["command"]["path"]),
         "wrong command or config"),
        (lambda request, value: request["argv"].append("shutdown"),
         "wrong command or config"),
        (lambda request, value: request.__setitem__("nonce", "A" * 64),
         "nonce"),
    ],
)
def test_launch_request_rejects_wrong_package_config_command_and_nonce(
        tmp_path: Path, mutator, message: str) -> None:
    value, request, _ = request_fixture(tmp_path)
    mutator(request, value)
    with pytest.raises(phase1c.Phase1CFailure, match=message):
        phase1c.validate_launch_request(request, value)


def test_launch_request_detects_config_and_command_mutation(tmp_path: Path) -> None:
    value, request, _ = request_fixture(tmp_path)
    Path(request["config"]["path"]).write_text("changed\n", encoding="utf-8")
    with pytest.raises(phase1c.Phase1CFailure, match="config"):
        phase1c.validate_launch_request(request, value)


def test_launch_request_structurally_refuses_scripts_search_and_extra_argv(
        tmp_path: Path) -> None:
    value, request, _ = request_fixture(tmp_path)
    with_scripts = copy.deepcopy(request)
    with_scripts["scripts"] = {"path": request["config"]["path"]}
    with pytest.raises(phase1c.Phase1CFailure, match="launch request keys differ"):
        phase1c.validate_launch_request(with_scripts, value)
    for extra in (["-s", request["config"]["path"]],
                  ["-c", "shutdown"], ["-f", request["command"]["path"]]):
        changed = copy.deepcopy(request)
        changed["argv"].extend(extra)
        changed["argv_sha256"] = hashlib.sha256(json.dumps(
            changed["argv"], separators=(",", ":")).encode()).hexdigest()
        with pytest.raises(phase1c.Phase1CFailure, match="wrong command or config argv"):
            phase1c.validate_launch_request(changed, value)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda go: go.__setitem__("authorization_state", "TEMPLATE_NOT_AUTHORIZED"),
         "not live"),
        (lambda go: go.__setitem__("package_id", "WRONG_PACKAGE_000"), "wrong package"),
        (lambda go: go.__setitem__("maximum_uses", 2), "one-shot"),
        (lambda go: go.__setitem__("board_contact_authorized", False), "does not permit"),
        (lambda go: go.__setitem__("expires_utc", "2026-08-28T11:59:00Z"),
         "not currently valid"),
    ],
)
def test_authorization_rejects_malformed_expired_and_wrong_package(
        tmp_path: Path, mutator, message: str) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, _ = authorization_fixture(tmp_path, value, request, request_path)
    mutator(go)
    with pytest.raises(phase1c.Phase1CFailure, match=message):
        phase1c.validate_authorization(go, request_path, request, value, NOW)


def test_authorization_requires_two_distinct_exact_audits(tmp_path: Path) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, _ = authorization_fixture(tmp_path, value, request, request_path)
    go["live_readiness_audits"][1] = copy.deepcopy(go["live_readiness_audits"][0])
    with pytest.raises(phase1c.Phase1CFailure, match="independent"):
        phase1c.validate_authorization(go, request_path, request, value, NOW)


def test_consumption_is_terminal_and_replay_rejects(tmp_path: Path) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, go_path = authorization_fixture(tmp_path, value, request, request_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    receipt = phase1c.consume_authorization(go_path, go, request_path, state, NOW)
    assert receipt.is_file()
    assert phase1c.load_json_strict(receipt)["state"] == "CONSUMED"
    assert phase1c.load_json_strict(state / "high-water.json")[
        "last_session_number"] == 1
    with pytest.raises(phase1c.Phase1CFailure, match="replayed or out of order"):
        phase1c.consume_authorization(go_path, go, request_path, state, NOW)


def test_late_high_water_failure_burns_authorization(tmp_path: Path,
                                                      monkeypatch) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, go_path = authorization_fixture(tmp_path, value, request, request_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    monkeypatch.setattr(phase1c, "_replace_write_through",
                        lambda *_args: (_ for _ in ()).throw(OSError("fault")))
    with pytest.raises(OSError, match="fault"):
        phase1c.consume_authorization(go_path, go, request_path, state, NOW)
    receipts = list((state / "receipts").glob("receipt-*.json"))
    assert len(receipts) == 1
    assert phase1c.load_json_strict(receipts[0])["state"] == "CONSUMED"


@pytest.mark.parametrize("backend_error", [
    phase1c.Phase1CFailure("CreateProcessW fault"),
    phase1c.Phase1CFailure("AssignProcessToJobObject fault"),
    phase1c.Phase1CFailure("parent death / Job closed"),
    phase1c.Phase1CFailure("earliest-main READY report timed out"),
])
def test_receipt_precedes_spawn_and_backend_fault_is_nonreplayable(
        tmp_path: Path, monkeypatch, backend_error: Exception) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, go_path = authorization_fixture(tmp_path, value, request, request_path)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, value)
    monkeypatch.setattr(phase1c, "MANIFEST_PATH", manifest_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    events = []

    def backend(**kwargs):
        assert kwargs["receipt_path"].is_file()
        events.append("backend")
        raise backend_error

    with pytest.raises(phase1c.Phase1CFailure, match=str(backend_error).split(" /")[0]):
        phase1c._launch_authorized_desk_test_only(
            go_path, request_path, state, Path(request["log"]["path"]), backend, NOW)
    assert events == ["backend"]
    assert len(list((state / "receipts").glob("receipt-*.json"))) == 1


def test_post_consumption_request_mutation_burns_and_never_spawns(
        tmp_path: Path, monkeypatch) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, go_path = authorization_fixture(tmp_path, value, request, request_path)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, value)
    monkeypatch.setattr(phase1c, "MANIFEST_PATH", manifest_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    original = phase1c.consume_authorization

    def consume(*args, **kwargs):
        receipt = original(*args, **kwargs)
        request_path.write_bytes(request_path.read_bytes() + b" ")
        return receipt

    monkeypatch.setattr(phase1c, "consume_authorization", consume)
    called = False

    def backend(**_kwargs):
        nonlocal called
        called = True
        return 0

    with pytest.raises(phase1c.Phase1CFailure, match="changed after"):
        phase1c._launch_authorized_desk_test_only(
            go_path, request_path, state, Path(request["log"]["path"]), backend, NOW)
    assert called is False
    assert len(list((state / "receipts").glob("receipt-*.json"))) == 1


def test_post_consumption_go_mutation_burns_and_never_spawns(
        tmp_path: Path, monkeypatch) -> None:
    value, request, request_path = request_fixture(tmp_path)
    go, go_path = authorization_fixture(tmp_path, value, request, request_path)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, value)
    monkeypatch.setattr(phase1c, "MANIFEST_PATH", manifest_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    original = phase1c.consume_authorization

    def consume(*args, **kwargs):
        receipt = original(*args, **kwargs)
        go_path.write_bytes(go_path.read_bytes() + b" ")
        return receipt

    monkeypatch.setattr(phase1c, "consume_authorization", consume)
    called = False

    def backend(**_kwargs):
        nonlocal called
        called = True
        return 0

    with pytest.raises(phase1c.Phase1CFailure, match="authorization changed after"):
        phase1c._launch_authorized_desk_test_only(
            go_path, request_path, state, Path(request["log"]["path"]), backend, NOW)
    assert called is False
    assert len(list((state / "receipts").glob("receipt-*.json"))) == 1


def test_win32_launcher_is_direct_suspended_job_first_and_fail_closed() -> None:
    source = phase1c.MANIFEST_PATH.with_name("phase1c_win32.py").read_text(
        encoding="utf-8")
    assert "subprocess.Popen" not in source
    assert "CreateProcessW" in source
    assert "AssignProcessToJobObject" in source
    assert "ResumeThread" in source
    assert source.index("AssignProcessToJobObject(wintypes.HANDLE(job)") < source.index(
        "ResumeThread(process.hThread)")
    assert "PROC_THREAD_ATTRIBUTE_HANDLE_LIST" in source or "0x00020002" in source
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in source or "0x00002000" in source
    assert "TerminateJobObject" in source
    assert "TerminateProcess(process.hProcess, 70)" in source
    assert "WaitForSingleObject(process.hProcess, 10000)" in source
    assert "receipt_path.is_file()" in source
    assert "_read_ready" in source and "_write_continue" in source


def test_namespace_custody_spans_consumption_and_backend_return(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value, request, request_path = request_fixture(tmp_path)
    _, go_path = authorization_fixture(tmp_path, value, request, request_path)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, value)
    monkeypatch.setattr(phase1c, "MANIFEST_PATH", manifest_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    events = []

    original_consume = phase1c.consume_authorization

    def consume(*args, **kwargs):
        events.append("consume")
        return original_consume(*args, **kwargs)

    monkeypatch.setattr(phase1c, "consume_authorization", consume)

    class Custody:
        def __enter__(self):
            events.append("custody-enter")
            return self

        def verify(self, **identities):
            assert set(identities) == {"openocd", "config", "command"}
            events.append("custody-verify")

        def __exit__(self, exc_type, exc, traceback):
            events.append("custody-close")
            return False

    def custody_factory(**paths):
        assert set(paths) == {"executable", "config", "command", "log_path"}
        assert paths["log_path"].as_posix() == request["log"]["path"]
        return Custody()

    def backend(**kwargs):
        assert kwargs["receipt_path"].is_file()
        events.append("backend")
        return 0

    result = phase1c._launch_authorized_desk_test_only(
        go_path, request_path, state, Path(request["log"]["path"]), backend,
        NOW, custody_factory)
    assert result == 0
    assert events == ["custody-enter", "custody-verify", "consume",
                      "custody-verify", "backend", "custody-close"]


def test_namespace_custody_closes_after_backend_fault(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value, request, request_path = request_fixture(tmp_path)
    _, go_path = authorization_fixture(tmp_path, value, request, request_path)
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, value)
    monkeypatch.setattr(phase1c, "MANIFEST_PATH", manifest_path)
    state = state_fixture(tmp_path, value["authorization_epoch"])
    events = []

    class Custody:
        def __enter__(self):
            events.append("enter")
            return self

        def verify(self, **_identities):
            events.append("verify")

        def __exit__(self, exc_type, exc, traceback):
            assert exc_type is phase1c.Phase1CFailure
            events.append("close")
            return False

    def backend(**_kwargs):
        events.append("backend")
        raise phase1c.Phase1CFailure("injected backend fault")

    with pytest.raises(phase1c.Phase1CFailure, match="injected backend fault"):
        phase1c._launch_authorized_desk_test_only(
            go_path, request_path, state, Path(request["log"]["path"]), backend,
            NOW, lambda **_paths: Custody())
    assert events == ["enter", "verify", "verify", "backend", "close"]
    assert len(list((state / "receipts").glob("receipt-*.json"))) == 1
