"""Verified installation and discovery of AGaMEMnon's patched OpenOCD."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile


DEFAULT_VERSION = "0.1.0"
REPOSITORY = "bbenchoff/AGaMEMnon"


def platform_key():
    machine = platform.machine().lower()
    if platform.system() == "Darwin":
        if machine in ("arm64", "aarch64"):
            return "macos-arm64", ".tar.gz"
        if machine in ("x86_64", "amd64"):
            return "macos-x64", ".tar.gz"
        raise RuntimeError(f"prebuilt OpenOCD is not published for macOS {platform.machine()}")
    if machine not in ("amd64", "x86_64"):
        raise RuntimeError(f"prebuilt OpenOCD is not published for {platform.machine()}")
    if os.name == "nt":
        return "windows-x64", ".zip"
    if platform.system() == "Linux":
        return "linux-x64", ".tar.gz"
    raise RuntimeError(f"prebuilt OpenOCD is not published for {platform.system()}")


def install_base():
    override = os.environ.get("AGAMEMNON_HOME")
    return Path(override).expanduser() if override else Path.home() / ".agamemnon"


def _receipt_path():
    return install_base() / "tools" / "openocd" / "current.json"


def discover_openocd():
    """Return (executable, scripts) for a verified AGaMEMnon install, if present."""
    receipt = _receipt_path()
    if not receipt.is_file():
        return None, None
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
        executable = Path(data["executable"])
        scripts = Path(data["scripts"])
    except (OSError, KeyError, ValueError, TypeError):
        return None, None
    if executable.is_file() and scripts.is_dir():
        return str(executable), str(scripts)
    return None, None


def _request(url, accept="application/octet-stream"):
    headers = {"User-Agent": "AGaMEMnon-installer"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def _download(url, destination):
    with urllib.request.urlopen(_request(url), timeout=60) as response:
        with Path(destination).open("wb") as stream:
            shutil.copyfileobj(response, stream)


def _release_urls(version, names):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        base = f"https://github.com/{REPOSITORY}/releases/download/openocd-v{version}"
        return {name: f"{base}/{name}" for name in names}
    api = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/openocd-v{version}"
    with urllib.request.urlopen(
        _request(api, "application/vnd.github+json"), timeout=30
    ) as response:
        release = json.load(response)
    assets = {item["name"]: item["url"] for item in release.get("assets", [])}
    missing = sorted(set(names) - set(assets))
    if missing:
        raise RuntimeError(f"release is missing assets: {', '.join(missing)}")
    return {name: assets[name] for name in names}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_destination(root, member):
    root = root.resolve()
    destination = (root / member).resolve()
    if destination != root and root not in destination.parents:
        raise RuntimeError(f"archive contains an unsafe path: {member}")


def _extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                _safe_destination(destination, member)
            bundle.extractall(destination)
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                _safe_destination(destination, member.name)
                if member.issym() or member.islnk():
                    raise RuntimeError(f"archive contains an unsupported link: {member.name}")
            bundle.extractall(destination)


def install_openocd(version=DEFAULT_VERSION, prefix=None, base_url=None):
    platform_name, suffix = platform_key()
    asset = f"agamemnon-openocd-{platform_name}{suffix}"
    if base_url:
        urls = {name: f"{base_url.rstrip('/')}/{name}"
                for name in (asset, asset + ".sha256")}
    else:
        urls = _release_urls(version, (asset, asset + ".sha256"))
    root = Path(prefix).expanduser().resolve() if prefix else (
        install_base() / "tools" / "openocd" / version
    )
    with tempfile.TemporaryDirectory(prefix="agamemnon-install-") as temporary:
        temporary = Path(temporary)
        archive = temporary / asset
        checksum = temporary / (asset + ".sha256")
        print(f"downloading {asset}")
        _download(urls[asset], archive)
        _download(urls[asset + ".sha256"], checksum)
        expected = checksum.read_text(encoding="ascii").split()[0].lower()
        actual = _sha256(archive)
        if actual != expected:
            raise RuntimeError(f"OpenOCD SHA-256 mismatch: got {actual}, expected {expected}")
        staging = temporary / "extract"
        _extract(archive, staging)
        candidates = list(staging.rglob("openocd.exe" if os.name == "nt" else "openocd"))
        candidates = [item for item in candidates if item.parent.name == "bin"]
        if len(candidates) != 1:
            raise RuntimeError(f"archive has {len(candidates)} OpenOCD executables; expected one")
        bundle_root = candidates[0].parent.parent
        if root.exists():
            raise RuntimeError(f"install destination already exists: {root}")
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(bundle_root), root)

    executable = root / "bin" / ("openocd.exe" if os.name == "nt" else "openocd")
    scripts = root / "share" / "openocd" / "scripts"
    if not executable.is_file() or not scripts.is_dir():
        raise RuntimeError("installed OpenOCD bundle is incomplete")
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    receipt = _receipt_path()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "schema": 1,
        "version": version,
        "platform": platform_name,
        "archive_sha256": actual,
        "executable": str(executable),
        "scripts": str(scripts),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"installed verified OpenOCD {version}: {executable}")
    if platform.system() == "Linux":
        print("Linux host libraries: libusb-1.0-0 and libhidapi-hidraw0; install the shipped udev rule if needed.")
    if platform.system() == "Darwin":
        print("macOS libusb and HIDAPI runtime libraries are included in this verified bundle.")
    return executable


def cmd_install_openocd(args):
    try:
        install_openocd(args.version, args.prefix, args.base_url)
    except Exception as exc:
        raise SystemExit(f"install failed: {exc}") from exc
