#!/usr/bin/env python3
"""Install and exercise an AGaMEMnon SDK archive without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sidecar(archive):
    sidecar = Path(str(archive) + ".sha256")
    if not sidecar.is_file():
        raise RuntimeError(f"missing archive checksum: {sidecar}")
    fields = sidecar.read_text(encoding="ascii").strip().split()
    if len(fields) < 2 or fields[1].lstrip("*") != archive.name:
        raise RuntimeError(f"checksum sidecar does not name {archive.name}")
    actual = sha256(archive)
    if fields[0].lower() != actual:
        raise RuntimeError(
            f"archive SHA-256 mismatch: expected {fields[0]}, got {actual}"
        )
    return actual


def _safe_destination(root, name):
    destination = (root / name).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"archive member escapes extraction root: {name}") from exc
    return destination


def extract_archive(archive, destination):
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                _safe_destination(destination, member.filename)
            bundle.extractall(destination)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, "r:*") as bundle:
            for member in bundle.getmembers():
                _safe_destination(destination, member.name)
                if member.issym() or member.islnk():
                    parent = _safe_destination(destination, member.name).parent
                    link = (parent / member.linkname).resolve()
                    try:
                        link.relative_to(destination.resolve())
                    except ValueError as exc:
                        raise RuntimeError(
                            f"archive link escapes extraction root: {member.name}"
                        ) from exc
            bundle.extractall(destination)
        return
    raise RuntimeError(f"unsupported archive format: {archive}")


def locate_bundle(extracted):
    matches = list(Path(extracted).rglob("BUNDLE_VERSION"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one bundle root, found {len(matches)} BUNDLE_VERSION files"
        )
    return matches[0].parent


def executable(root, relative):
    plain = root / relative
    windows = Path(str(plain) + ".exe")
    if windows.is_file():
        return windows
    if plain.is_file():
        return plain
    raise RuntimeError(f"bundle executable missing: {plain}[.exe]")


def run(command, cwd=None, env=None, capture=False):
    print("+ " + " ".join(str(item) for item in command))
    return subprocess.run(
        [str(item) for item in command],
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def smoke(bundle, workspace, python=sys.executable):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    version = (bundle / "BUNDLE_VERSION").read_text(encoding="ascii").strip()
    if version != manifest["bundle_version"]:
        raise RuntimeError("BUNDLE_VERSION does not match manifest.json")
    json.loads((bundle / "COMPONENTS.json").read_text(encoding="utf-8"))

    venv = workspace / "venv"
    run([python, "-m", "venv", venv])
    venv_python = executable(venv, "Scripts/python" if os.name == "nt" else "bin/python")
    packages = bundle / "packages"
    wheels = sorted(packages.glob("agamemnon_ag32-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one AGaMEMnon wheel, found {len(wheels)}")
    run([
        venv_python, "-m", "pip", "install", "--no-index",
        "--find-links", packages, wheels[0],
    ])

    env = dict(os.environ)
    env["PIP_NO_INDEX"] = "1"
    env["AGAMEMNON_OSS"] = str(bundle / "tools" / "oss-cad-suite")
    env["AGAMEMNON_UARCH_NEXTPNR"] = str(
        executable(bundle, "tools/nextpnr/nextpnr-generic")
    )
    runtime = bundle / "tools" / "nextpnr" / "runtime"
    if runtime.is_dir():
        env["AGAMEMNON_UARCH_NEXTPNR_RUNTIME"] = str(runtime)
    riscv_bin = bundle / "tools" / "riscv" / "bin"
    env["PATH"] = os.pathsep.join([str(riscv_bin), env.get("PATH", "")])
    cli = [venv_python, "-m", "agamemnon.cli"]

    result = run(cli + ["--version"], env=env, capture=True)
    if result.stdout.strip() != f"agamemnon {version}":
        raise RuntimeError(f"wheel version does not match bundle: {result.stdout!r}")

    doctor = run(
        cli + ["doctor", "--no-hardware", "--json"], env=env, capture=True
    )
    report = json.loads(doctor.stdout)
    missing = [
        name for name in ("inspect", "mcu-build", "fpga-build")
        if not report["tiers"][name]["ready"]
    ]
    if missing:
        raise RuntimeError("bundle capability tiers not ready: " + ", ".join(missing))

    fixture = bundle / "smoke" / "counter_ahb_routed.json"
    run(cli + ["verify", fixture, "--cycles", "8"], env=env)

    projects = workspace / "projects"
    projects.mkdir()
    run(cli + ["new", projects / "mcu", "--template", "mcu-blink"], env=env)
    run(cli + ["build"], cwd=projects / "mcu", env=env)
    if not (projects / "mcu" / "build" / "mcu.bin").is_file():
        raise RuntimeError("MCU template did not produce build/mcu.bin")

    run(cli + ["new", projects / "fpga", "--template", "fpga-blink"], env=env)
    run(cli + ["build"], cwd=projects / "fpga", env=env)
    for output in ("mcu.bin", "fabric.bin"):
        if not (projects / "fpga" / "build" / output).is_file():
            raise RuntimeError(f"FPGA template did not produce build/{output}")

    return {
        "bundle_version": version,
        "doctor_tiers": report["tiers"],
        "offline_install": True,
        "offline_verify": True,
        "mcu_compile": True,
        "fpga_compile": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument(
        "--work",
        help="working directory to retain (default: temporary and removed)",
    )
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    archive = Path(args.archive).resolve()
    digest = verify_sidecar(archive)

    if args.work:
        workspace = Path(args.work).resolve()
        if workspace.exists() and any(workspace.iterdir()):
            raise RuntimeError(f"--work directory is not empty: {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        extract_archive(archive, workspace / "extract")
        result = smoke(locate_bundle(workspace / "extract"), workspace, args.python)
    else:
        with tempfile.TemporaryDirectory(prefix="agamemnon-bundle-smoke-") as temp:
            workspace = Path(temp)
            extract_archive(archive, workspace / "extract")
            result = smoke(locate_bundle(workspace / "extract"), workspace, args.python)

    result["archive_sha256"] = digest
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
