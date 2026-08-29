"""Direct suspended Windows launcher for the R6 Phase1C earliest-main gate.

Importing this module has no process, USB, registry, or device side effects.  The
sole launch entry uses CreateProcessW directly; it never delegates to Popen.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time

from tools.openocd.r6_live_boundary.phase1c import (
    CONTINUE_TOKEN, Phase1CFailure, READY_MAGIC, require,
)


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    kernel32 = None


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW),
                ("lpAttributeList", wintypes.LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _configure_api() -> None:
    if kernel32 is None:
        return
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE),
                                    ctypes.POINTER(wintypes.HANDLE),
                                    ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]
    kernel32.CreatePipe.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD,
                                     wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t)]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID,
        ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
        wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                       wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD),
                                       wintypes.LPVOID]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    for name in ("ReadFile", "WriteFile"):
        function = getattr(kernel32, name)
        function.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        function.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL


_configure_api()


def _error(label: str) -> Phase1CFailure:
    return Phase1CFailure(f"{label} failed: {ctypes.get_last_error()}")


def _close(handle: int | None) -> None:
    if handle and kernel32 is not None:
        kernel32.CloseHandle(wintypes.HANDLE(handle))


def _pipe() -> tuple[int, int]:
    attributes = SECURITY_ATTRIBUTES(
        ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    read = wintypes.HANDLE()
    write = wintypes.HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(read), ctypes.byref(write),
                               ctypes.byref(attributes), 0):
        raise _error("CreatePipe")
    return int(read.value), int(write.value)


def _make_parent_only(handle: int) -> None:
    if not kernel32.SetHandleInformation(wintypes.HANDLE(handle), 1, 0):
        raise _error("SetHandleInformation")


def _create_log(path: Path) -> int:
    attributes = SECURITY_ATTRIBUTES(
        ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    handle = kernel32.CreateFileW(
        str(path), 0x40000000, 0x1, ctypes.byref(attributes), 1,
        0x00000080 | 0x80000000, None)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise _error("CreateFileW launch log")
    raw = int(handle)
    try:
        from tools.openocd.r6_live_boundary.phase1c_namespace import (
            verify_open_handle_path,
        )
        verify_open_handle_path(raw, path, directory=False)
    except BaseException:
        _close(raw)
        raise
    return raw


def _create_stdin_null() -> int:
    attributes = SECURITY_ATTRIBUTES(
        ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    handle = kernel32.CreateFileW(
        "NUL", 0x80000000, 0x1 | 0x2, ctypes.byref(attributes), 3,
        0x00000080, None)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise _error("CreateFileW NUL")
    return int(handle)


def _create_job() -> int:
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise _error("CreateJobObjectW")
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        _close(int(handle))
        raise _error("SetInformationJobObject")
    return int(handle)


def _attribute_list(handles: list[int]) -> tuple[ctypes.Array, wintypes.LPVOID,
                                                  ctypes.Array]:
    size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    pointer = ctypes.cast(buffer, wintypes.LPVOID)
    if not kernel32.InitializeProcThreadAttributeList(pointer, 1, 0,
                                                       ctypes.byref(size)):
        raise _error("InitializeProcThreadAttributeList")
    array_type = wintypes.HANDLE * len(handles)
    handle_array = array_type(*(wintypes.HANDLE(item) for item in handles))
    if not kernel32.UpdateProcThreadAttribute(
            pointer, 0, 0x00020002, ctypes.byref(handle_array),
            ctypes.sizeof(handle_array), None, None):
        kernel32.DeleteProcThreadAttributeList(pointer)
        raise _error("UpdateProcThreadAttribute handle list")
    return buffer, pointer, handle_array


def _environment() -> ctypes.Array:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    require(bool(system_root), "SystemRoot is unavailable")
    root = Path(system_root).resolve().as_posix()
    drive = Path(system_root).drive
    require(bool(drive), "SystemDrive is unavailable")
    values = {
        "PATH": f"{root}/System32",
        "SystemDrive": drive,
        "SystemRoot": root,
        "WINDIR": root,
    }
    raw = "\0".join(f"{key}={values[key]}" for key in sorted(values,
                                                               key=str.casefold))
    return ctypes.create_unicode_buffer(raw + "\0\0")


def _read_ready(read_handle: int, nonce: str, process: int,
                timeout_seconds: float = 10.0) -> None:
    expected = READY_MAGIC + nonce.encode("ascii")
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    available = wintypes.DWORD()
    while len(output) < len(expected):
        if time.monotonic() >= deadline:
            raise Phase1CFailure("earliest-main READY report timed out")
        if kernel32.WaitForSingleObject(wintypes.HANDLE(process), 0) == 0:
            raise Phase1CFailure("child exited before earliest-main READY")
        if not kernel32.PeekNamedPipe(wintypes.HANDLE(read_handle), None, 0, None,
                                      ctypes.byref(available), None):
            raise _error("PeekNamedPipe")
        if not available.value:
            time.sleep(0.01)
            continue
        remaining = len(expected) - len(output)
        block = ctypes.create_string_buffer(min(remaining, available.value))
        consumed = wintypes.DWORD()
        if not kernel32.ReadFile(wintypes.HANDLE(read_handle), block, len(block),
                                 ctypes.byref(consumed), None):
            raise _error("ReadFile READY")
        output.extend(block.raw[:consumed.value])
    require(bytes(output) == expected, "earliest-main READY report differs")


def _write_continue(write_handle: int) -> None:
    written = wintypes.DWORD()
    raw = ctypes.create_string_buffer(CONTINUE_TOKEN)
    if not kernel32.WriteFile(wintypes.HANDLE(write_handle), raw,
                              len(CONTINUE_TOKEN), ctypes.byref(written), None):
        raise _error("WriteFile CONTINUE")
    require(written.value == len(CONTINUE_TOKEN), "CONTINUE write was partial")


def launch_process(*, executable: Path, argv: list[str], nonce: str, log_path: Path,
                   cwd: Path, receipt_path: Path) -> int:
    """Consume no authority itself; caller must supply an existing terminal receipt."""
    require(os.name == "nt" and kernel32 is not None, "launcher requires Windows")
    require(receipt_path.is_file(), "terminal receipt is missing before CreateProcess")
    require(len(argv) == 4 and argv[0::2] == ["-f", "-f"],
            "launch argv escaped the exact grammar")
    require(len(nonce) == 64 and all(item in "0123456789abcdef" for item in nonce),
            "launch nonce is malformed")

    handles: list[int] = []
    attribute_pointer = None
    attribute_buffer = None
    attribute_handles = None
    process = PROCESS_INFORMATION()
    job = None
    try:
        control_read, control_write = _pipe()
        handles.extend([control_read, control_write])
        report_read, report_write = _pipe()
        handles.extend([report_read, report_write])
        _make_parent_only(control_write)
        _make_parent_only(report_read)
        log = _create_log(log_path)
        handles.append(log)
        stdin_null = _create_stdin_null()
        handles.append(stdin_null)
        job = _create_job()
        handles.append(job)

        inherited = [control_read, report_write, stdin_null, log]
        attribute_buffer, attribute_pointer, attribute_handles = _attribute_list(inherited)
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        startup.StartupInfo.dwFlags = 0x00000100
        startup.StartupInfo.hStdInput = wintypes.HANDLE(stdin_null)
        startup.StartupInfo.hStdOutput = wintypes.HANDLE(log)
        startup.StartupInfo.hStdError = wintypes.HANDLE(log)
        startup.lpAttributeList = attribute_pointer

        gate = [
            f"--r6-gate-read-handle={control_read}",
            f"--r6-gate-write-handle={report_write}",
            f"--r6-gate-nonce={nonce}",
        ]
        command_line = subprocess.list2cmdline([str(executable), *gate, *argv])
        mutable_command = ctypes.create_unicode_buffer(command_line)
        environment = _environment()
        flags = 0x00000004 | 0x00000400 | 0x00080000 | 0x08000000
        if not kernel32.CreateProcessW(
                str(executable), mutable_command, None, None, True, flags,
                environment, str(cwd), ctypes.byref(startup.StartupInfo),
                ctypes.byref(process)):
            raise _error("CreateProcessW")
        if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), process.hProcess):
            raise _error("AssignProcessToJobObject")
        if kernel32.ResumeThread(process.hThread) != 1:
            raise _error("ResumeThread")

        _close(control_read)
        handles.remove(control_read)
        _close(report_write)
        handles.remove(report_write)
        _close(stdin_null)
        handles.remove(stdin_null)
        _close(log)
        handles.remove(log)
        _read_ready(report_read, nonce, int(process.hProcess))
        _write_continue(control_write)
        _close(control_write)
        handles.remove(control_write)
        _close(report_read)
        handles.remove(report_read)

        wait = kernel32.WaitForSingleObject(process.hProcess, 120000)
        if wait == 0x00000102:
            raise Phase1CFailure("OpenOCD child timed out")
        require(wait == 0, f"OpenOCD wait failed: {wait}")
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code)):
            raise _error("GetExitCodeProcess")
        return int(code.value)
    except BaseException:
        if job:
            kernel32.TerminateJobObject(wintypes.HANDLE(job), 70)
        if process.hProcess:
            kernel32.TerminateProcess(process.hProcess, 70)
            kernel32.WaitForSingleObject(process.hProcess, 10000)
        raise
    finally:
        if attribute_pointer:
            kernel32.DeleteProcThreadAttributeList(attribute_pointer)
        _close(int(process.hThread) if process.hThread else None)
        _close(int(process.hProcess) if process.hProcess else None)
        for handle in reversed(handles):
            _close(handle)
        del attribute_buffer, attribute_handles
