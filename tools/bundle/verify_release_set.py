#!/usr/bin/env python3
"""Fail closed unless a tagged wheel and both SDK archives are one release."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _toml(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - release job uses Python 3.12
        import tomli as tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))


def wheel_version(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        metadata = [name for name in wheel.namelist()
                    if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("wheel must contain exactly one METADATA file")
        fields = wheel.read(metadata[0]).decode("utf-8").splitlines()
    versions = [line.split(":", 1)[1].strip()
                for line in fields if line.startswith("Version:")]
    if len(versions) != 1 or not versions[0]:
        raise ValueError("wheel METADATA must contain exactly one version")
    return versions[0]


def embedded_wheel(archive: Path) -> tuple[str, str]:
    """Return (member name, SHA-256) for the archive's one AGaMEMnon wheel."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            names = [name for name in bundle.namelist()
                     if "/packages/agamemnon_ag32-" in name
                     and name.endswith(".whl")]
            if len(names) != 1:
                raise ValueError(f"{archive.name} must contain one AGaMEMnon wheel")
            data = bundle.read(names[0])
            return names[0], sha256_bytes(data)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, "r:*") as bundle:
            members = [item for item in bundle.getmembers()
                       if item.isfile()
                       and "/packages/agamemnon_ag32-" in item.name
                       and item.name.endswith(".whl")]
            if len(members) != 1:
                raise ValueError(f"{archive.name} must contain one AGaMEMnon wheel")
            stream = bundle.extractfile(members[0])
            if stream is None:
                raise ValueError(f"cannot read embedded wheel in {archive.name}")
            return members[0].name, sha256_bytes(stream.read())
    raise ValueError(f"unsupported SDK archive: {archive}")


def verify(tag: str, wheel: Path, linux: Path, windows: Path,
           pyproject: Path, manifest: Path) -> dict:
    project_version = _toml(pyproject)["project"]["version"]
    bundle_version = json.loads(manifest.read_text(encoding="utf-8"))["bundle_version"]
    wheel_data = wheel.read_bytes()
    packaged_version = wheel_version(wheel_data)
    expected_tag = "v" + project_version
    if not (tag == expected_tag and bundle_version == project_version
            and packaged_version == project_version):
        raise ValueError(
            "release identity mismatch: tag=%s project=%s bundle=%s wheel=%s" %
            (tag, project_version, bundle_version, packaged_version)
        )
    published_hash = sha256_bytes(wheel_data)
    embedded = {}
    for name, archive in (("linux", linux), ("windows", windows)):
        member, digest = embedded_wheel(archive)
        if digest != published_hash:
            raise ValueError(
                f"{name} SDK embeds wheel {digest}, published wheel is {published_hash}"
            )
        embedded[name] = {"member": member, "sha256": digest}
    return {
        "tag": tag,
        "version": project_version,
        "wheel_sha256": published_hash,
        "embedded": embedded,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--manifest", type=Path,
                        default=Path("tools/bundle/manifest.json"))
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.tag, args.wheel, args.linux, args.windows,
                            args.pyproject, args.manifest), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
