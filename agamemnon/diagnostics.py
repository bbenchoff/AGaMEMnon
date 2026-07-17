"""Host and hardware diagnostics for ``agamemnon doctor``."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

from . import __version__


def _split_command(value):
    if os.name == "nt" and Path(value).exists():
        return [value]
    return shlex.split(value, posix=os.name != "nt")


def _run(command, env=None, timeout=8):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env=env
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def _first_line(text):
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _tool(name, env_var=None, oss_subdir="bin"):
    if env_var and os.environ.get(env_var):
        return _split_command(os.environ[env_var])[0]
    if name == "openocd":
        from .tool_install import discover_openocd
        installed, _ = discover_openocd()
        if installed:
            return installed
    pio = Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio")) / "packages"
    pio_packages = {
        "riscv64-unknown-elf-gcc": "toolchain-agrv/bin",
        "openocd": "tool-agrv_openocd/bin",
    }
    if name in pio_packages:
        for suffix in (name, name + ".exe"):
            candidate = pio / pio_packages[name] / suffix
            if candidate.is_file():
                return str(candidate)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for suffix in (name, name + ".exe"):
            candidate = Path(oss) / oss_subdir / suffix
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def _oss_env(runtime=None):
    env = dict(os.environ)
    paths = []
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        paths.extend((str(Path(oss) / "bin"), str(Path(oss) / "lib")))
    if runtime:
        paths.insert(0, runtime)
    if paths:
        env["PATH"] = os.pathsep.join([*paths, env.get("PATH", "")])
    return env


def _native_env(runtime=None):
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    unwanted = set()
    if oss:
        unwanted = {
            os.path.normcase(os.path.normpath(str(Path(oss) / "bin"))),
            os.path.normcase(os.path.normpath(str(Path(oss) / "lib"))),
        }
    entries = [item for item in env.get("PATH", "").split(os.pathsep)
               if item and os.path.normcase(os.path.normpath(item)) not in unwanted]
    if runtime:
        entries.insert(0, runtime)
    env["PATH"] = os.pathsep.join(entries)
    return env


def _serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = []
    for port in list_ports.comports():
        ports.append({
            "device": port.device,
            "vid": port.vid,
            "pid": port.pid,
            "description": port.description or "",
            "manufacturer": port.manufacturer or "",
            "product": port.product or "",
        })
    return ports


def collect(hardware=True, uart_port=None, probe_dap=False):
    root = Path(__file__).resolve().parent
    checks = []

    def add(name, status, detail, required=False, data=None):
        checks.append({
            "name": name, "status": status, "detail": detail,
            "required": required, "data": data,
        })

    py_ok = sys.version_info >= (3, 8)
    add("Python", "PASS" if py_ok else "FAIL", platform.python_version(), True)
    add("AGaMEMnon", "PASS", __version__, True)
    add("host", "INFO", f"{platform.system()} {platform.machine()} ({platform.release()})")

    chipdb = root / "chipdb" / "fabric_default.bin"
    chipdb_ok = False
    if not chipdb.exists():
        add("chip database", "FAIL", f"missing {chipdb}", True)
    else:
        head = chipdb.read_bytes()[:80]
        if head.startswith(b"version https://git-lfs.github.com/spec"):
            add("chip database", "FAIL", "Git LFS pointer present; run 'git lfs pull'", True)
        else:
            chipdb_ok = True
            add("chip database", "PASS", f"baseline {chipdb.stat().st_size} bytes", True)

    yosys = _tool("yosys")
    yosys_ready = False
    if yosys:
        ok, output = _run([yosys, "-V"], env=_oss_env())
        yosys_ready = ok
        add("Yosys", "PASS" if ok else "WARN", _first_line(output) or yosys)
    else:
        add("Yosys", "WARN", "not found; FPGA builds unavailable; set AGAMEMNON_OSS")

    nextpnr_value = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    nextpnr = _split_command(nextpnr_value)[0] if nextpnr_value else shutil.which("nextpnr-generic")
    nextpnr_ready = False
    if nextpnr:
        command = _split_command(nextpnr_value) if nextpnr_value else [nextpnr]
        runtime = os.environ.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
        ok, output = _run(command + ["--version"], env=_native_env(runtime))
        nextpnr_ready = ok
        hint = _first_line(output) or " ".join(command)
        if not ok and sys.platform == "win32":
            hint += "; check AGAMEMNON_UARCH_NEXTPNR_RUNTIME"
        add("AGRV2K nextpnr", "PASS" if ok else "WARN", hint)
    else:
        add("AGRV2K nextpnr", "WARN", "not found; FPGA builds unavailable; set AGAMEMNON_UARCH_NEXTPNR")

    gcc = _tool("riscv64-unknown-elf-gcc")
    gcc_ready = False
    if gcc:
        ok, output = _run([gcc, "--version"])
        gcc_ready = ok
        add("RISC-V GCC", "PASS" if ok else "WARN", _first_line(output) or gcc)
    else:
        add("RISC-V GCC", "WARN", "not found; MCU examples cannot build")

    openocd = _tool("openocd", "AGAMEMNON_OPENOCD")
    openocd_dap_ready = False
    if openocd:
        ok, output = _run([openocd, "--version"], timeout=5)
        add("OpenOCD", "PASS" if ok else "WARN", _first_line(output) or openocd)
        try:
            dap_option = b"-dap" in Path(openocd).read_bytes()
        except OSError:
            dap_option = False
        openocd_dap_ready = ok and dap_option
        add("OpenOCD AGM DAP", "PASS" if dap_option else "WARN",
            "riscv -dap option present" if dap_option else "could not confirm required riscv -dap option")
    else:
        add("OpenOCD", "WARN", "not found; DAP/SWD programming unavailable")

    ports = _serial_ports()
    usb_ports = []
    pico_ports = []
    if ports is None:
        add("pyserial", "WARN", "not installed; install agamemnon-ag32[programming]")
    else:
        add("serial ports", "INFO", f"{len(ports)} found", data=ports)
        for port in ports:
            text = " ".join(str(port.get(k) or "") for k in ("description", "manufacturer", "product")).lower()
            if (port["vid"], port["pid"]) == (0xCAFE, 0x4001) or "agm uploader" in text or "uploader cdc" in text:
                usb_ports.append(port["device"])
            if port["vid"] == 0x2E8A or "raspberry pi pico" in text or "pico 2" in text:
                pico_ports.append(port["device"])
        add("USB CDC uploader", "PASS" if usb_ports else "INFO",
            ", ".join(usb_ports) if usb_ports else "not enumerated", data=usb_ports)
        add("Pico UART bridge", "PASS" if pico_ports else "INFO",
            ", ".join(pico_ports) if pico_ports else "not enumerated", data=pico_ports)

    if hardware:
        if usb_ports:
            try:
                from .usb_program import identify
                info = identify(usb_ports[0])
                add("AG32 over USB", "PASS", info)
            except Exception as exc:
                add("AG32 over USB", "WARN", str(exc))
        if openocd and (probe_dap or not usb_ports):
            try:
                from . import program
                result = program._oocd(
                    ["init", "halt", "mdw 0x03000100", "resume", "shutdown"], timeout=8
                )
                words = program._mem(result.stdout + result.stderr)
                devid = words.get(program.DEVID_ADDR)
                add("AG32 over DAP", "PASS" if devid == 0x40200001 else "INFO",
                    f"DEVICE_ID=0x{devid:08x}" if devid is not None else "not detected")
            except Exception as exc:
                add("AG32 over DAP", "INFO", f"not detected ({exc})")
        elif openocd:
            add("AG32 over DAP", "INFO", "not probed; USB identified the target (use --probe-dap to test DAP too)")
        if uart_port:
            try:
                from .uart_program import PicoUartBridge, AG32Bootloader
                with PicoUartBridge(uart_port) as bridge:
                    loader = AG32Bootloader(bridge)
                    loader.connect()
                    ident = loader.get_id().hex()
                    bridge.run_application()
                add("AG32 over UART", "PASS", f"device ID 0x{ident} via {uart_port}")
            except Exception as exc:
                add("AG32 over UART", "WARN", str(exc))

    core_ready = py_ok and chipdb_ok
    tiers = {
        "inspect": {
            "ready": core_ready,
            "detail": "bitstream inspection, conversion, project creation, and offline verification",
        },
        "mcu-build": {
            "ready": core_ready and gcc_ready,
            "detail": "RISC-V firmware compilation",
        },
        "fpga-build": {
            "ready": core_ready and yosys_ready and nextpnr_ready,
            "detail": "Verilog synthesis, place/route, and bit generation",
        },
        "dap-program": {
            "ready": core_ready and openocd_dap_ready,
            "detail": "SWD/DAP programming host path (target presence reported separately)",
        },
        "usb-program": {
            "ready": core_ready and ports is not None,
            "detail": "USB CDC host support"
            + (f"; target on {', '.join(usb_ports)}" if usb_ports else "; no uploader target enumerated"),
        },
        "uart-program": {
            "ready": core_ready and ports is not None,
            "detail": "Pico UART host support"
            + (f"; bridge on {', '.join(pico_ports)}" if pico_ports else "; no Pico bridge enumerated"),
        },
    }
    return {
        "version": __version__,
        "ok": core_ready,
        "tiers": tiers,
        "checks": checks,
    }


def cmd_doctor(args):
    report = collect(
        hardware=not args.no_hardware, uart_port=args.uart_port,
        probe_dap=args.probe_dap,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for check in report["checks"]:
            print(f"[{check['status']:<4}] {check['name']:<20} {check['detail']}")
        print("\ncapability tiers:")
        for name, tier in report["tiers"].items():
            status = "READY" if tier["ready"] else "MISS"
            print(f"[{status:<5}] {name:<16} {tier['detail']}")
    if not report["ok"]:
        raise SystemExit(1)
