from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tarfile
import zipfile

import pytest

from agamemnon import tool_install
from tools.bundle.build_bundle import validate_openocd_arguments
from tools.bundle.openocd_audit import classify_dap_probe, validate_corresponding_source
from tools.openocd.release import make_sbom, manifest, patch_hashes


ROOT = Path(__file__).resolve().parents[1]


def test_dap_parser_probe_classifies_compatible_and_stock_output():
    assert classify_dap_probe("Error: DAP name invalid!") is True
    assert classify_dap_probe("Error: unknown option -dap") is False
    assert classify_dap_probe("unrelated startup failure") is None


def test_corresponding_source_requires_license_and_riscv_dap_source(tmp_path):
    with pytest.raises(RuntimeError, match="GPL license"):
        validate_corresponding_source(tmp_path)
    (tmp_path / "COPYING").write_text("GPL-2.0", encoding="utf-8")
    with pytest.raises(RuntimeError, match="riscv.c"):
        validate_corresponding_source(tmp_path)
    source = tmp_path / "src" / "target" / "riscv" / "riscv.c"
    source.parent.mkdir(parents=True)
    source.write_text("/* RISC-V target with ADIv5 DAP support. */", encoding="utf-8")
    assert validate_corresponding_source(tmp_path) == tmp_path.resolve()


def test_bundle_can_omit_openocd_but_never_ship_an_unpaired_binary():
    assert validate_openocd_arguments(None, None) is False
    assert validate_openocd_arguments("openocd", "source") is True
    with pytest.raises(ValueError, match="supplied together"):
        validate_openocd_arguments("openocd", None)
    with pytest.raises(ValueError, match="supplied together"):
        validate_openocd_arguments(None, "source")


def test_build_only_bundle_omits_openocd_activation(tmp_path):
    oss = tmp_path / "oss"
    toolchain = tmp_path / "toolchain"
    oss.mkdir()
    toolchain.mkdir()
    nextpnr = tmp_path / "nextpnr-generic.exe"
    wheel = tmp_path / "agamemnon_ag32-test.whl"
    nextpnr.write_bytes(b"nextpnr fixture")
    wheel.write_bytes(b"wheel fixture")
    output = tmp_path / "sdk"

    subprocess.run(
        [
            sys.executable,
            "tools/bundle/build_bundle.py",
            "--oss", str(oss),
            "--nextpnr", str(nextpnr),
            "--toolchain", str(toolchain),
            "--wheel", str(wheel),
            "--output", str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    powershell = (output / "activate.ps1").read_text(encoding="utf-8")
    shell = (output / "activate.sh").read_text(encoding="utf-8")
    assert "AGAMEMNON_OPENOCD" not in powershell
    assert "AGAMEMNON_OPENOCD" not in shell
    archive_suffix = ".zip" if sys.platform == "win32" else ".tar.gz"
    archive = Path(str(output) + archive_suffix)
    assert archive.is_file()
    assert Path(str(archive) + ".sha256").is_file()


def test_openocd_release_pins_official_base_gerrit_and_nonrelease_oracle():
    data = manifest()
    assert data["openocd"]["base_commit"] == "a17c5f5a6dac6625cd5b01dfc3234f57cb58f1f3"
    assert data["openocd"]["gerrit_commit"] == "9aa0f9765801e06ad79775ee0dde95de9a2a0a66"
    assert data["openocd"]["patched_commit"] == "f96d840a24e0c6694815293b803e18b535663c00"
    assert data["oracle"]["redistribute"] is False
    assert len(patch_hashes(data)) == 2
    assert all(len(value) == 64 for value in patch_hashes(data).values())
    assert set(data["macos_runtime_licenses"]) == {"libusb", "hidapi"}
    for licenses in data["macos_runtime_licenses"].values():
        assert licenses
        assert all(len(item["sha256"]) == 64 for item in licenses)
    assert set(data["macos_runtime_sources"]) == {"libusb", "hidapi"}
    assert all(
        len(item["sha256"]) == 64
        for item in data["macos_runtime_sources"].values()
    )


def test_openocd_release_wires_both_macos_archives_and_current_runners():
    bundle = json.loads(
        (ROOT / "tools" / "bundle" / "manifest.json").read_text(encoding="utf-8")
    )
    installer = bundle["pins"]["openocd"]["installer"]
    assert installer["macos_arm64_asset"] == "agamemnon-openocd-macos-arm64.tar.gz"
    assert installer["macos_x64_asset"] == "agamemnon-openocd-macos-x64.tar.gz"

    workflow = (
        ROOT / ".github" / "workflows" / "openocd-release.yml"
    ).read_text(encoding="utf-8")
    assert "runner: macos-14" in workflow
    assert "runner: macos-15-intel" in workflow
    assert "runner: macos-13\n" not in workflow
    assert "agamemnon-openocd-macos-arm64.tar.gz" in workflow
    assert "agamemnon-openocd-macos-x64.tar.gz" in workflow

    build_script = (
        ROOT / "tools" / "openocd" / "build.sh"
    ).read_text(encoding="utf-8")
    assert "install_name_tool -change" in build_script
    assert "DYLD_PRINT_LIBRARIES=1" in build_script
    assert 'manifest["macos_runtime_licenses"]' in build_script
    assert 'manifest["macos_runtime_sources"]' in build_script
    assert "share/licenses/libusb" in build_script
    assert "share/licenses/hidapi" in build_script


def test_openocd_sbom_assigns_bundled_runtime_files_to_their_packages(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "share" / "sources").mkdir(parents=True)
    (tmp_path / "bin" / "openocd").write_bytes(b"openocd")
    (tmp_path / "lib" / "libusb-1.0.0.dylib").write_bytes(b"libusb")
    (tmp_path / "lib" / "libhidapi.0.dylib").write_bytes(b"hidapi")
    (tmp_path / "share" / "sources" / "libusb-1.0.30.tar.bz2").write_bytes(
        b"libusb source"
    )
    (tmp_path / "share" / "sources" / "hidapi-0.15.0.tar.gz").write_bytes(
        b"hidapi source"
    )

    make_sbom(tmp_path, "macos-arm64")
    sbom = json.loads((tmp_path / "openocd.spdx.json").read_text(encoding="utf-8"))
    files = {item["SPDXID"]: item["fileName"] for item in sbom["files"]}
    owners = {
        files[item["relatedSpdxElement"]]: item["spdxElementId"]
        for item in sbom["relationships"]
        if item["relationshipType"] == "CONTAINS"
    }
    assert owners["./bin/openocd"] == "SPDXRef-Package-OpenOCD"
    assert owners["./lib/libusb-1.0.0.dylib"] == "SPDXRef-Package-libusb"
    assert owners["./lib/libhidapi.0.dylib"] == "SPDXRef-Package-hidapi"
    packages = {item["SPDXID"]: item for item in sbom["packages"]}
    assert packages["SPDXRef-Package-libusb"]["filesAnalyzed"] is True
    assert packages["SPDXRef-Package-hidapi"]["filesAnalyzed"] is True
    assert len(
        packages["SPDXRef-Package-libusb"]["packageVerificationCode"][
            "packageVerificationCodeValue"
        ]
    ) == 40
    assert any(
        item["spdxElementId"] == "SPDXRef-DOCUMENT"
        and item["relationshipType"] == "DESCRIBES"
        and item["relatedSpdxElement"] == "SPDXRef-Package-OpenOCD"
        for item in sbom["relationships"]
    )


def test_verified_openocd_installer_and_discovery(tmp_path, monkeypatch):
    monkeypatch.setenv("AGAMEMNON_HOME", str(tmp_path / "home"))
    platform_name, suffix = tool_install.platform_key()
    asset = f"agamemnon-openocd-{platform_name}{suffix}"
    release = tmp_path / "release"
    bundle = tmp_path / f"agamemnon-openocd-{platform_name}"
    executable = bundle / "bin" / ("openocd.exe" if sys.platform == "win32" else "openocd")
    scripts = bundle / "share" / "openocd" / "scripts"
    scripts.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"qualified OpenOCD fixture")
    release.mkdir()
    archive = release / asset
    if suffix == ".zip":
        with zipfile.ZipFile(archive, "w") as output:
            for item in (executable, scripts / ".keep"):
                if item.name == ".keep":
                    item.write_text("", encoding="utf-8")
                output.write(item, item.relative_to(bundle.parent))
    else:
        (scripts / ".keep").write_text("", encoding="utf-8")
        with tarfile.open(archive, "w:gz") as output:
            output.add(bundle, arcname=bundle.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / (asset + ".sha256")).write_text(
        f"{digest}  {asset}\n", encoding="ascii"
    )

    installed = tool_install.install_openocd(
        version="test",
        prefix=tmp_path / "installed",
        base_url=release.as_uri(),
    )
    discovered, discovered_scripts = tool_install.discover_openocd()
    assert installed == Path(discovered)
    assert Path(discovered_scripts).is_dir()
    receipt = json.loads(
        (tmp_path / "home" / "tools" / "openocd" / "current.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["archive_sha256"] == digest


@pytest.mark.parametrize("system,machine,os_name,expected", [
    ("Windows", "AMD64", "nt", ("windows-x64", ".zip")),
    ("Linux", "x86_64", "posix", ("linux-x64", ".tar.gz")),
    ("Darwin", "arm64", "posix", ("macos-arm64", ".tar.gz")),
    ("Darwin", "aarch64", "posix", ("macos-arm64", ".tar.gz")),
    ("Darwin", "x86_64", "posix", ("macos-x64", ".tar.gz")),
])
def test_platform_key_maps_supported_platforms(monkeypatch, system, machine, os_name, expected):
    monkeypatch.setattr(tool_install.platform, "system", lambda: system)
    monkeypatch.setattr(tool_install.platform, "machine", lambda: machine)
    monkeypatch.setattr(tool_install.os, "name", os_name)
    assert tool_install.platform_key() == expected


@pytest.mark.parametrize("system,machine", [
    ("Linux", "aarch64"),       # no arm64 Linux binary published
    ("Darwin", "i386"),         # unsupported macOS arch
    ("FreeBSD", "amd64"),       # unsupported OS
])
def test_platform_key_rejects_unpublished_platforms(monkeypatch, system, machine):
    monkeypatch.setattr(tool_install.platform, "system", lambda: system)
    monkeypatch.setattr(tool_install.platform, "machine", lambda: machine)
    monkeypatch.setattr(tool_install.os, "name", "posix")
    with pytest.raises(RuntimeError, match="not published"):
        tool_install.platform_key()
