from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

from agamemnon import project


ROOT = Path(__file__).resolve().parents[1]


def test_cli_version():
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "--version"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "agamemnon 0.1.0"


def test_riscv_tool_discovery_accepts_cross_platform_xpack_prefix(monkeypatch):
    monkeypatch.setattr(
        project.shutil,
        "which",
        lambda name: "/sdk/bin/riscv-none-elf-gcc"
        if name == "riscv-none-elf-gcc" else None,
    )
    assert project.find_riscv_tool(
        "riscv64-unknown-elf-gcc"
    ) == "/sdk/bin/riscv-none-elf-gcc"


def test_default_march_accounts_for_modern_explicit_zicsr(monkeypatch):
    def version(value):
        return SimpleNamespace(stdout=value, returncode=0)

    monkeypatch.setattr(project.subprocess, "run", lambda *args, **kwargs: version("15.2.0\n"))
    assert project.default_riscv_march("gcc") == "rv32imac_zicsr"
    monkeypatch.setattr(project.subprocess, "run", lambda *args, **kwargs: version("11.1.0\n"))
    assert project.default_riscv_march("gcc") == "rv32imac"


def test_new_mcu_fpga_alias_creates_loadable_project(tmp_path):
    destination = tmp_path / "hello"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    assert loaded.name == "hello"
    assert loaded.project["device"] == "AGRV2KL48"
    assert [Path(item).name for item in loaded.fabric["sources"]] == ["top.v"]
    assert loaded.fabric["top"] == "top"
    assert loaded.fabric["freq"] == 10
    assert "sysclk" not in loaded.fabric
    assert loaded.mcu["linker"] == "@sdk/link_sram.ld"


def test_all_maintained_template_payloads_exist():
    root = ROOT / "agamemnon" / "templates"
    for name in project.TEMPLATE_NAMES:
        payload = "mcu-fpga-registers" if name == "mcu-fpga" else name
        assert (root / payload).is_dir(), name
        assert (root / payload / "agamemnon.toml").is_file(), name


def test_project_frequency_can_be_overridden_from_the_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("AGAMEMNON_DEVICE", "restore-after-test")
    monkeypatch.setenv("AGAMEMNON_HSE", "7")
    destination = tmp_path / "hello"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="fpga-blink", board="ag32vf303-l48"
    ))
    args = SimpleNamespace(freq=25)
    loaded = project.Project.load(destination)

    assert project.apply_fabric_config(args, loaded)
    assert args.freq == 25


def test_synthesis_scripts_accept_explicit_top():
    for name in ("synth_pads.tcl", "synth_generic.tcl"):
        text = (ROOT / "agamemnon" / "synth" / name).read_text(encoding="utf-8")
        assert "hierarchy -check -top $TOP" in text


def test_padded_synthesis_resolves_assets_from_tcl_script_path():
    text = (ROOT / "agamemnon" / "synth" / "synth_pads.tcl").read_text(
        encoding="utf-8"
    )
    assert "[info script]" in text
    assert "$argv0" not in text


def test_project_flash_layout_records_hashes_and_rejects_overlap(tmp_path):
    root = tmp_path / "layout"
    root.mkdir()
    (root / "mcu.bin").write_bytes(b"mcu")
    (root / "fabric.bin").write_bytes(b"fabric")
    data = {
        "project": {"name": "layout", "board": "ag32vf303-l48"},
        "flash": {"mcu_address": 0x80000000, "fabric_address": 0x80001000},
    }
    loaded = project.Project(root, data)
    output = project.write_flash_plan(
        loaded, str(root / "mcu.bin"), str(root / "fabric.bin")
    )
    text = Path(output).read_text(encoding="utf-8")
    assert '"address": 2147483648' in text
    assert '"sha256"' in text

    loaded.flash["fabric_address"] = 0x80000002
    try:
        project.write_flash_plan(loaded, str(root / "mcu.bin"), str(root / "fabric.bin"))
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("overlapping flash regions were accepted")
