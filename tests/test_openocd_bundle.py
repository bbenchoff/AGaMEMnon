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
from tools.openocd.release import manifest, patch_hashes


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
