"""Assemble a relocatable AGaMEMnon release bundle from pinned tool trees."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

try:
    from .openocd_audit import audit as audit_openocd
except ImportError:  # Direct execution: python tools/bundle/build_bundle.py
    from openocd_audit import audit as audit_openocd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def copy(source, destination):
    source = Path(source).resolve()
    if not source.exists():
        raise SystemExit(f"bundle input does not exist: {source}")
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def validate_openocd_arguments(openocd, openocd_source):
    """Accept no OpenOCD, or a binary paired with its corresponding source."""
    if bool(openocd) != bool(openocd_source):
        raise ValueError("--openocd and --openocd-source must be supplied together")
    return bool(openocd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oss", required=True, help="OSS CAD Suite root")
    parser.add_argument("--nextpnr", required=True, help="AGRV2K nextpnr executable")
    parser.add_argument("--nextpnr-runtime", help="matching runtime DLL directory")
    parser.add_argument("--toolchain", required=True, help="RISC-V toolchain root")
    parser.add_argument(
        "--openocd",
        help="optional compatible OpenOCD root; omit for a build-only SDK",
    )
    parser.add_argument(
        "--openocd-source",
        help="unpacked corresponding GPL source for the exact compatible OpenOCD build",
    )
    parser.add_argument("--wheel", required=True, help="AGaMEMnon wheel")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        has_openocd = validate_openocd_arguments(args.openocd, args.openocd_source)
        openocd_source = None
        if has_openocd:
            _, openocd_source = audit_openocd(args.openocd, args.openocd_source)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"OpenOCD bundle preflight failed: {exc}") from exc

    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy(args.oss, output / "tools" / "oss-cad-suite")
    copy(args.nextpnr, output / "tools" / "nextpnr" / Path(args.nextpnr).name)
    if args.nextpnr_runtime:
        copy(args.nextpnr_runtime, output / "tools" / "nextpnr" / "runtime")
    copy(args.toolchain, output / "tools" / "riscv")
    if has_openocd:
        copy(args.openocd, output / "tools" / "openocd")
        copy(openocd_source, output / "sources" / "openocd")
    copy(args.wheel, output / "packages" / Path(args.wheel).name)
    copy(HERE / "manifest.json", output / "manifest.json")
    copy(ROOT / "docs" / "INSTALLATION.md", output / "INSTALLATION.md")

    powershell_activation = (
        "$Root = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
        "$env:AGAMEMNON_OSS = Join-Path $Root 'tools/oss-cad-suite'\n"
        "$env:AGAMEMNON_UARCH_NEXTPNR = Join-Path $Root 'tools/nextpnr/nextpnr-generic.exe'\n"
        "$env:AGAMEMNON_UARCH_NEXTPNR_RUNTIME = Join-Path $Root 'tools/nextpnr/runtime'\n"
        "$env:PATH = (Join-Path $Root 'tools/riscv/bin') + ';' + $env:PATH\n"
    )
    shell_activation = (
        "ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "export AGAMEMNON_OSS=\"$ROOT/tools/oss-cad-suite\"\n"
        "export AGAMEMNON_UARCH_NEXTPNR=\"$ROOT/tools/nextpnr/nextpnr-generic\"\n"
        "export AGAMEMNON_UARCH_NEXTPNR_RUNTIME=\"$ROOT/tools/nextpnr/runtime\"\n"
        "export PATH=\"$ROOT/tools/riscv/bin:$PATH\"\n"
    )
    if has_openocd:
        powershell_activation += (
            "$env:AGAMEMNON_OPENOCD = Join-Path $Root 'tools/openocd/bin/openocd.exe'\n"
            "$env:AGAMEMNON_OOCD_SCRIPTS = Join-Path $Root 'tools/openocd/share/openocd/scripts'\n"
        )
        shell_activation += (
            "export AGAMEMNON_OPENOCD=\"$ROOT/tools/openocd/bin/openocd\"\n"
            "export AGAMEMNON_OOCD_SCRIPTS=\"$ROOT/tools/openocd/share/openocd/scripts\"\n"
        )
    (output / "activate.ps1").write_text(powershell_activation, encoding="utf-8")
    (output / "activate.sh").write_text(shell_activation, encoding="utf-8")
    with open(HERE / "manifest.json", encoding="utf-8") as source:
        manifest = json.load(source)
    (output / "BUNDLE_VERSION").write_text(manifest["bundle_version"] + "\n", encoding="ascii")
    archive = shutil.make_archive(str(output), "zip" if sys.platform == "win32" else "gztar", output.parent, output.name)
    digest = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    Path(archive + ".sha256").write_text(f"{digest}  {Path(archive).name}\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
