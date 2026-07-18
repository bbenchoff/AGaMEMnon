#!/usr/bin/env python3
"""Download and verify the pinned host tools used by an SDK bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform as host_platform
import subprocess
import tarfile
import urllib.request
import zipfile


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, output, expected):
    output = Path(output)
    if output.is_file() and sha256(output) == expected:
        print(f"cached {output.name}")
        return output
    request = urllib.request.Request(
        url, headers={"User-Agent": "AGaMEMnon-SDK-bundle-builder"}
    )
    temporary = output.with_suffix(output.suffix + ".part")
    with urllib.request.urlopen(request) as response, temporary.open("wb") as sink:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            sink.write(block)
    actual = sha256(temporary)
    if actual != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"{output.name} SHA-256 mismatch: expected {expected}, got {actual}"
        )
    temporary.replace(output)
    return output


def _safe_destination(root, name):
    destination = (root / name).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"archive member escapes extraction root: {name}") from exc
    return destination


def extract(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                _safe_destination(destination, member.filename)
            source.extractall(destination)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, "r:*") as source:
            for member in source.getmembers():
                _safe_destination(destination, member.name)
                if member.issym() or member.islnk():
                    link = (_safe_destination(destination, member.name).parent /
                            member.linkname).resolve()
                    try:
                        link.relative_to(destination.resolve())
                    except ValueError as exc:
                        raise RuntimeError(
                            f"archive link escapes extraction root: {member.name}"
                        ) from exc
            source.extractall(destination)
        return
    if os.name == "nt" and str(archive).lower().endswith(".exe"):
        subprocess.run(
            [str(Path(archive).resolve()), f"-o{destination.resolve()}", "-y"],
            check=True,
        )
        return
    raise RuntimeError(f"unsupported tool archive: {archive}")


def _platform_key(value):
    if value:
        return value
    system = host_platform.system()
    machine = host_platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise RuntimeError(f"unsupported bundle host architecture: {machine}")
    if system == "Windows":
        return "windows-x64"
    if system == "Linux":
        return "linux-x64"
    raise RuntimeError(f"unsupported bundle host: {system}")


def _find_root(root, relative):
    matches = list(Path(root).rglob(relative))
    matches.extend(Path(root).rglob(relative + ".exe"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {relative}[.exe], found {len(matches)}")
    return matches[0].parents[len(Path(relative).parts) - 1]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["windows-x64", "linux-x64"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache")
    parser.add_argument("--json-output")
    args = parser.parse_args(argv)
    key = _platform_key(args.platform)
    output = Path(args.output).resolve()
    cache = Path(args.cache).resolve() if args.cache else output / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    extract_root = output / "extracted"
    if extract_root.exists() and any(extract_root.iterdir()):
        raise RuntimeError(f"tool extraction directory is not empty: {extract_root}")
    extract_root.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pins = manifest["pins"]
    inputs = (
        (
            "oss_cad_suite",
            pins["oss_cad_suite"],
            "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/"
            f"{pins['oss_cad_suite']['version']}",
        ),
        (
            "riscv_toolchain",
            pins["riscv_toolchain"],
            "https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/"
            f"{pins['riscv_toolchain']['tag']}",
        ),
    )
    archives = {}
    for name, pin, base in inputs:
        asset = pin["assets"][key]
        archives[name] = download(
            f"{base}/{asset['name']}", cache / asset["name"], asset["sha256"]
        )
        extract(archives[name], extract_root / name)

    result = {
        "platform": key,
        "oss": str(_find_root(
            extract_root / "oss_cad_suite", "bin/yosys"
        )),
        "toolchain": str(_find_root(
            extract_root / "riscv_toolchain", "bin/riscv-none-elf-gcc"
        )),
        "archives": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in archives.items()
        },
    }
    text = json.dumps(result, indent=2) + "\n"
    if args.json_output:
        Path(args.json_output).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
