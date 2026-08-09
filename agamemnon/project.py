"""Manifest-backed AGaMEMnon projects and beginner workflow commands."""

from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

from .engine.registry import CONSTANTS


MANIFEST = "agamemnon.toml"
TEMPLATE_NAMES = (
    "mcu-blink", "fpga-blink", "mcu-fpga", "mcu-fpga-registers", "uart", "usb-cdc", "safe-recovery"
)


def _toml_load(path):
    try:
        import tomllib
    except ImportError:  # Python 3.8-3.10
        import tomli as tomllib
    with open(path, "rb") as source:
        return tomllib.load(source)


class Project:
    def __init__(self, root, data):
        self.root = Path(root).resolve()
        self.data = data
        self.project = data.get("project", {})
        self.fabric = data.get("fabric", {})
        self.mcu = data.get("mcu", {})
        self.flash = data.get("flash", {})
        self.external = data.get("external", {})
        board_id = self.project.get("board", "ag32vf303-l48")
        board_path = sdk_root() / "boards" / (board_id + ".toml")
        if not board_path.is_file():
            raise ValueError(f"unknown board {board_id!r}; no manifest {board_path}")
        self.board = _toml_load(board_path)["board"]

    @classmethod
    def load(cls, path=None):
        path = Path(path or MANIFEST)
        if path.is_dir():
            path = path / MANIFEST
        if not path.is_file():
            raise FileNotFoundError(
                f"no {MANIFEST} found; pass a Verilog file or run 'agamemnon new NAME'"
            )
        return cls(path.parent, _toml_load(path))

    def path(self, value):
        return str((self.root / value).resolve())

    @property
    def name(self):
        return self.project.get("name", self.root.name)


def find_riscv_tool(name):
    names = [name]
    if name.startswith("riscv64-unknown-elf-"):
        names.append(name.replace("riscv64-unknown-elf-", "riscv-none-elf-", 1))
    for candidate_name in names:
        command = shutil.which(candidate_name)
        if command:
            return command
    pio = Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))
    for candidate_name in names:
        candidate = pio / "packages" / "toolchain-agrv" / "bin" / (
            candidate_name + (".exe" if os.name == "nt" else "")
        )
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError(
        f"cannot find {' or '.join(names)}; install the AGaMEMnon tool bundle "
        "or AGM PlatformIO toolchain"
    )


def sdk_root():
    return Path(__file__).resolve().parent / "sdk"


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_artifact(project, relative):
    path = (project.root / relative).resolve()
    try:
        path.relative_to(project.root)
    except ValueError as exc:
        raise ValueError(
            f"qualified profile artifact escapes the project: {relative}"
        ) from exc
    return path


def build_qualified_fabric(project):
    """Strictly replay one immutable, hash-bound routed profile if selected.

    This is deliberately separate from generic ``mcu_bridge`` routing. The
    profile registry admits an exact L48 route and output hash; changing the
    source, routed JSON, device, or board fails before an image is retained.
    """
    profile_id = project.fabric.get("qualified_profile")
    if not profile_id:
        return None
    output = Path(project.path(project.fabric.get("output", "build/fabric.bin")))
    compressed = Path(str(output) + ".comp")
    for stale in (output, compressed):
        stale.unlink(missing_ok=True)
    registry_path = sdk_root() / "qualified_fabric_profiles.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema") != 1:
        raise ValueError("unsupported qualified fabric profile registry")
    profile = registry.get("profiles", {}).get(profile_id)
    if profile is None:
        raise ValueError(f"unknown qualified fabric profile {profile_id!r}")

    board_id = project.project.get("board", "ag32vf303-l48")
    device = project.project.get("device", project.board["device"])
    if board_id != profile["board"] or device != profile["device"]:
        raise ValueError(
            f"qualified fabric profile {profile_id!r} is restricted to "
            f"{profile['board']} / {profile['device']}"
        )
    registered_image = CONSTANTS["l48_id_scratch8_image_sha256"].value
    if profile["image_sha256"] != registered_image:
        raise ValueError("qualified profile image hash disagrees with the claim registry")

    for key, hash_key in (("source", "source_sha256"), ("routed", "routed_sha256")):
        path = _project_artifact(project, profile[key])
        if not path.is_file():
            raise FileNotFoundError(f"qualified profile is missing {key}: {path}")
        actual = _sha256_file(path)
        if actual != profile[hash_key]:
            raise ValueError(
                f"qualified profile {key} hash mismatch: expected "
                f"{profile[hash_key]}, got {actual}"
            )

    routed = _project_artifact(project, profile["routed"])
    output.parent.mkdir(parents=True, exist_ok=True)

    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("AGAMEMNON_")
    }
    package_parent = Path(__file__).resolve().parent.parent
    env["PYTHONPATH"] = os.pathsep.join(
        [str(package_parent), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", str(routed), str(output)],
        cwd=project.root,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        for stale in (output, compressed):
            stale.unlink(missing_ok=True)
        raise RuntimeError(
            "qualified profile strict replay failed:\n" + result.stdout + result.stderr
        )

    checks = (
        (output, profile["image_bytes"], profile["image_sha256"]),
        (compressed, profile["compressed_bytes"], profile["compressed_sha256"]),
    )
    for path, expected_bytes, expected_sha256 in checks:
        actual_bytes = path.stat().st_size if path.is_file() else None
        actual_sha256 = _sha256_file(path) if path.is_file() else None
        if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
            for stale in (output, compressed):
                stale.unlink(missing_ok=True)
            raise RuntimeError(
                f"qualified profile output mismatch for {path.name}: expected "
                f"{expected_bytes} bytes / {expected_sha256}, got "
                f"{actual_bytes} / {actual_sha256}"
            )
    print(
        f"[project] qualified fabric {profile_id} -> {output} "
        f"(sha256 {profile['image_sha256']})"
    )
    return str(output)


def default_riscv_march(gcc):
    """Account for the CSR extension split in modern RISC-V binutils."""
    try:
        result = subprocess.run(
            [gcc, "-dumpversion"], capture_output=True, text=True, check=True
        )
        major = int(result.stdout.strip().split(".", 1)[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        major = 0
    return "rv32imac_zicsr" if major >= 12 else "rv32imac"


def build_mcu(project):
    config = project.mcu
    if not config or not config.get("sources"):
        return None
    gcc = find_riscv_tool("riscv64-unknown-elf-gcc")
    objcopy = find_riscv_tool("riscv64-unknown-elf-objcopy")
    sources = [project.path(item) for item in config["sources"]]
    linker_value = config.get("linker", "@sdk/link_sram.ld")
    linker = str(sdk_root() / linker_value[5:]) if linker_value.startswith("@sdk/") else project.path(linker_value)
    output = project.path(config.get("output", "build/mcu.bin"))
    elf = str(Path(output).with_suffix(".elf"))
    map_file = str(Path(output).with_suffix(".map"))
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    includes = [project.root, sdk_root() / "include"]
    includes.extend(project.root / item for item in config.get("include_dirs", []))
    command = [
        gcc,
        "-march=" + config.get("march", default_riscv_march(gcc)),
        "-mabi=" + config.get("mabi", "ilp32"),
        "-Os", "-g", "-nostdlib", "-ffreestanding", "-fno-builtin",
        "-ffunction-sections", "-fdata-sections",
    ]
    for include in includes:
        command += ["-I", str(include)]
    command += [
        "-T", linker, "-Wl,--gc-sections", f"-Wl,-Map,{map_file}",
        str(sdk_root() / "startup.S"), *sources, "-o", elf,
    ]
    print("[project] MCU: " + " ".join(Path(x).name if os.sep in x else x for x in command))
    subprocess.run(command, cwd=project.root, check=True)
    subprocess.run([objcopy, "-O", "binary", elf, output], cwd=project.root, check=True)
    print(f"[project] MCU -> {output} ({Path(output).stat().st_size} bytes)")
    return output


def build_external(project):
    command = project.external.get("command")
    if not command:
        return None
    executable = shutil.which(command[0])
    if not executable:
        raise FileNotFoundError(
            f"external backend '{command[0]}' is not installed; see {project.root / 'README.md'}"
        )
    resolved = [executable, *command[1:]]
    print("[project] external: " + " ".join(resolved))
    subprocess.run(resolved, cwd=project.root, check=True)
    return True


def write_flash_plan(project, mcu_output=None, fabric_output=None):
    if not project.flash:
        return None
    regions = []
    for name, path, key in (
        ("mcu", mcu_output, "mcu_address"),
        ("fabric", fabric_output, "fabric_address"),
    ):
        if not path or not Path(path).is_file() or key not in project.flash:
            continue
        data = Path(path).read_bytes()
        address = int(project.flash[key])
        end = address + len(data)
        if address < 0x80000000 or end > 0x80040000:
            raise ValueError(f"{name} region 0x{address:08x}..0x{end:08x} is outside main flash")
        regions.append({
            "name": name, "file": str(Path(path).relative_to(project.root)),
            "address": address, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    ordered = sorted(regions, key=lambda item: item["address"])
    for previous, current in zip(ordered, ordered[1:]):
        if previous["address"] + previous["size"] > current["address"]:
            raise ValueError(f"flash regions {previous['name']} and {current['name']} overlap")
    path = project.root / project.flash.get("plan", "build/flash-layout.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": 1, "project": project.name, "flash_base": 0x80000000,
        "flash_size": 0x40000, "regions": ordered,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"[project] flash layout -> {path}")
    return str(path)


def apply_fabric_config(args, project):
    config = project.fabric
    sources = config.get("sources", [])
    if not sources:
        return False
    args.input = project.path(sources[0])
    args.sources = [project.path(item) for item in sources[1:]]
    args.top = config.get("top")
    args.output = project.path(config.get("output", "build/fabric.bin"))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    args.pcf = project.path(config["pcf"]) if config.get("pcf") else None
    args.uarch = config.get("uarch", True)
    args.mcu = config.get("mcu_bridge", False)
    args.leds = config.get("leds", False)
    if getattr(args, "freq", None) is None:
        args.freq = config.get("freq")
    args.hard_carry = config.get("hard_carry", False)
    os.environ["AGAMEMNON_DEVICE"] = project.project.get("device", project.board["device"])
    if config.get("sysclk"):
        os.environ["AGAMEMNON_SYSCLK"] = str(config["sysclk"])
    if config.get("hse"):
        os.environ["AGAMEMNON_HSE"] = str(config["hse"])
    return True


def cmd_new(args):
    if args.template not in TEMPLATE_NAMES:
        raise SystemExit("unknown template; choose " + ", ".join(TEMPLATE_NAMES))
    destination = Path(args.name).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty directory {destination}")
    payload = "mcu-fpga-registers" if args.template == "mcu-fpga" else args.template
    source = Path(__file__).resolve().parent / "templates" / payload
    if not source.is_dir():
        raise SystemExit(f"template payload missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    manifest = destination / MANIFEST
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8").replace("@PROJECT_NAME@", destination.name)
        manifest.write_text(text, encoding="utf-8")
    print(f"created {args.template} project in {destination}")
    print(f"next: cd {destination.name} && agamemnon doctor && agamemnon build")


def cmd_monitor(args):
    try:
        import serial
        from serial.tools import list_ports
    except ImportError as exc:
        raise SystemExit("monitor requires pyserial; install agamemnon-ag32[programming]") from exc
    port = args.port
    if not port:
        candidates = [item.device for item in list_ports.comports()]
        if len(candidates) != 1:
            raise SystemExit("pass --port (available: " + ", ".join(candidates) + ")")
        port = candidates[0]
    print(f"monitoring {port} at {args.baud} baud; Ctrl-C exits")
    with serial.Serial(port, args.baud, timeout=0.1) as stream:
        try:
            while True:
                data = stream.read(4096)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
        except KeyboardInterrupt:
            print("\nmonitor closed")


def cmd_run(args):
    project = Project.load(args.project)
    mcu = project.path(project.mcu.get("output", "build/mcu.bin")) if project.mcu else None
    fabric = project.path(project.fabric.get("output", "build/fabric.bin")) if project.fabric else None
    if args.transport == "dap":
        if not mcu or not Path(mcu).is_file():
            raise SystemExit("DAP run needs a built MCU image; run 'agamemnon build'")
        from types import SimpleNamespace
        from . import program
        program.cmd_sram(SimpleNamespace(
            firmware=mcu, fabric=fabric if fabric and Path(fabric).is_file() else None,
            words=args.words, sleep=args.sleep,
        ))
        return
    if args.transport == "usb":
        from types import SimpleNamespace
        from . import usb_program
        address = int(project.flash.get("mcu_address", 0x80010000))
        if args.flash:
            if not args.backup:
                raise SystemExit("USB run with --flash requires --backup")
            usb_program.cmd_usb_flash(SimpleNamespace(
                image=mcu, addr=hex(address), backup=args.backup, port=args.port
            ))
        usb_program.cmd_usb_go(SimpleNamespace(addr=hex(address), port=args.port))
        return
    raise SystemExit("project run currently supports --transport dap or usb; use uart-flash for ROM recovery")
