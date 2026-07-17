from pathlib import Path
import subprocess
import sys

import pytest

from tools.bundle.build_bundle import validate_openocd_arguments
from tools.bundle.openocd_audit import classify_dap_probe, validate_corresponding_source


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
