from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys

import pytest

from agamemnon import project


ROOT = Path(__file__).resolve().parents[1]


def test_cli_version():
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "--version"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "agamemnon 0.3.0"


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
    assert loaded.fabric["qualified_profile"] == "l48-public32-exact-map-2026-08-15"
    assert "mcu_bridge" not in loaded.fabric
    assert loaded.mcu["linker"] == "@sdk/link_sram.ld"


def test_qualified_mcu_fpga_profile_replays_exact_image(tmp_path):
    destination = tmp_path / "registers"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    output = Path(project.build_qualified_fabric(loaded))
    assert output.stat().st_size == 99_944
    assert project._sha256_file(output) == (
        "ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5"
    )
    assert project._sha256_file(Path(str(output) + ".comp")) == (
        "ee5c464337ac389464f7d95ca522416752e6c62307ce3e2048a4e51aefdf6cba"
    )


def test_legacy_mcu_fpga_profile_remains_replayable(tmp_path):
    destination = tmp_path / "registers"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    loaded.fabric["qualified_profile"] = "l48-complete-byte-waited-2026-08-05"
    output = Path(project.build_qualified_fabric(loaded))
    assert project._sha256_file(output) == (
        "7d6cd01be47998176120324f8a131843cc96248221645e9f040cdf3950c99d81"
    )
    assert project._sha256_file(Path(str(output) + ".comp")) == (
        "962bbe0ffb86a26b8acd9fabeabf250b66e37212566d4c64b8b71699f60b6cf1"
    )


def test_qualified_serv_profile_replays_exact_image(tmp_path, monkeypatch):
    destination = tmp_path / "serv"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="serv-blinky", board="ag32vf303-l48"
    ))
    monkeypatch.setenv("AGAMEMNON_ALLOW_UNMAPPED", "1")
    monkeypatch.setenv("AGAMEMNON_SYSCLK", "123")
    loaded = project.Project.load(destination)
    assert loaded.fabric["qualified_profile"] == "l48-serv-blinky-2026-07-15"
    output = Path(project.build_qualified_fabric(loaded))
    assert output.stat().st_size == 99_944
    assert project._sha256_file(output) == (
        "fe7ecca298dc5bd929a12c3bf63c90a8323180a93016defa977de59580aa3d5a"
    )
    compressed = Path(str(output) + ".comp")
    assert compressed.stat().st_size == 9_722
    assert project._sha256_file(compressed) == (
        "2985f92decb6104b94647d9681ccd77d3a7f7246147cf027eebf90fda116d6b0"
    )


def test_qualified_mcu_fpga_profile_rejects_source_drift(tmp_path):
    destination = tmp_path / "registers"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    output = Path(project.build_qualified_fabric(loaded))
    source = destination / "logic" / "top.v"
    source.write_text(source.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
    try:
        project.build_qualified_fabric(loaded)
    except ValueError as exc:
        assert "source hash mismatch" in str(exc)
    else:
        raise AssertionError("qualified profile accepted modified source")
    assert not output.exists()
    assert not Path(str(output) + ".comp").exists()


def test_check_qualified_profile_mcu_pairing_rejects_default_main_against_gpio5_profile(tmp_path):
    """T15: the gpio5-w1c derivative retires the base profile's AHB bit1 W1C hook that the
    default src/main.c self-test relies on. Leaving [mcu].sources on the default main.c while
    pointing [fabric].qualified_profile at that derivative used to build fine and only fail on
    hardware with a confusing result[7] mismatch outside the selected profile's documented scope;
    this must now fail fast, before any board time is spent."""
    destination = tmp_path / "gpio5-mismatch"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    profile_id = "l48-public32-gpio5-w1c-exact-map-2026-08-15"
    with pytest.raises(ValueError, match="designed to pair with"):
        project.check_qualified_profile_mcu_pairing(loaded, profile_id)


def test_check_qualified_profile_mcu_pairing_rejects_default_main_against_autoevent_profile(tmp_path):
    destination = tmp_path / "autoevent-mismatch"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    profile_id = "l48-public32-autoevent-w1c-exact-map-2026-08-16"
    with pytest.raises(ValueError, match="designed to pair with"):
        project.check_qualified_profile_mcu_pairing(loaded, profile_id)


def test_check_qualified_profile_mcu_pairing_accepts_matching_companion_source(tmp_path):
    destination = tmp_path / "gpio5-matched"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    loaded.mcu["sources"] = ["src/main_gpio5_w1c.c"]
    project.check_qualified_profile_mcu_pairing(
        loaded, "l48-public32-gpio5-w1c-exact-map-2026-08-15"
    )  # must not raise


def test_check_qualified_profile_mcu_pairing_accepts_default_pairing(tmp_path):
    destination = tmp_path / "base-matched"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    project.check_qualified_profile_mcu_pairing(
        loaded, "l48-public32-exact-map-2026-08-15"
    )  # must not raise; this is the shipped default pairing


def test_check_qualified_profile_mcu_pairing_skips_profiles_without_a_companion(tmp_path):
    """Profiles with no matching template firmware example (public16, complete-byte-waited) or
    that back a non-firmware template (serv-blinky) are not cross-checked."""
    destination = tmp_path / "no-companion"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    for profile_id in (
        "l48-complete-byte-waited-2026-08-05",
        "l48-public16-exact-map-2026-08-15",
        "l48-serv-blinky-2026-07-15",
    ):
        project.check_qualified_profile_mcu_pairing(loaded, profile_id)  # must not raise


def test_cli_build_rejects_mismatched_qualified_profile_and_main_source(tmp_path):
    """End-to-end guard on the actual `agamemnon build` entry point, not just the direct
    function call -- this is what a user or agent editing agamemnon.toml by hand actually runs."""
    destination = tmp_path / "cli-gpio5-mismatch"
    subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "new", str(destination),
         "--board", "ag32vf303-l48", "--template", "mcu-fpga"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    manifest = destination / "agamemnon.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'qualified_profile = "l48-public32-exact-map-2026-08-15"',
            'qualified_profile = "l48-public32-gpio5-w1c-exact-map-2026-08-15"',
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "build"],
        cwd=destination, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "designed to pair with" in result.stdout


def test_qualified_serv_profile_rejects_bundled_rtl_drift(tmp_path):
    destination = tmp_path / "serv"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="serv-blinky", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    output = Path(project.build_qualified_fabric(loaded))
    source = destination / "logic" / "serv_rtl.v"
    source.write_text(source.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
    try:
        project.build_qualified_fabric(loaded)
    except ValueError as exc:
        assert "source hash mismatch" in str(exc)
    else:
        raise AssertionError("qualified SERV profile accepted modified bundled RTL")
    assert not output.exists()
    assert not Path(str(output) + ".comp").exists()


def test_legacy_qualified_profile_hashes_bind_the_silicon_evidence():
    profile = json.loads(
        (ROOT / "agamemnon" / "sdk" / "qualified_fabric_profiles.json").read_text(
            encoding="utf-8"
        )
    )["profiles"]["l48-complete-byte-waited-2026-08-05"]
    evidence = [
        json.loads(line)
        for line in (
            ROOT / "qualification" / "mcu_ahb_register_bank_evidence.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(
        row for row in evidence
        if row["trial_id"] == "2026-08-05-l48-combined-bank-one-wait-complete-byte"
    )
    assert profile["source_sha256"] == project._sha256_file(
        ROOT / "qualification" / "mcu_ahb_register_bank_combined_wait.v"
    )
    assert profile["source_sha256"] == project._sha256_file(
        ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
        "logic" / "complete_byte_waited8.v"
    )
    assert profile["evidence_routed_sha256"] == record["routed_sha256"]
    assert profile["image_sha256"] == record["bitstream_sha256"]

    regression = json.loads(
        (ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8")
    )
    packed = next(
        row for row in regression["artifacts"]
        if row["routed"] ==
        "qualification/mcu_ahb_register_bank_complete_byte_waited_routed.json"
    )
    assert profile["routed_sha256"] == packed["routed_sha256"]
    assert profile["image_sha256"] == packed["bitstream_sha256"]


def test_public16_profile_hashes_bind_the_silicon_evidence():
    profile = json.loads(
        (ROOT / "agamemnon" / "sdk" / "qualified_fabric_profiles.json").read_text(
            encoding="utf-8"
        )
    )["profiles"]["l48-public16-exact-map-2026-08-15"]
    evidence = [
        json.loads(line)
        for line in (
            ROOT / "qualification" / "mcu_ahb_public16_evidence.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(
        row for row in evidence
        if row["trial_id"] == "mcu-ahb-public16-exact-map-silicon-20260815"
    )
    source = (
        ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
        "logic" / "public16_exact_map.v"
    )
    routed = (
        ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
        "logic" / "public16_exact_map_L48_routed.json"
    )
    assert profile["source_sha256"] == project._sha256_file(source)
    assert profile["source_sha256"] == record["source_sha256"]
    assert profile["routed_sha256"] == project._sha256_file(routed)
    assert profile["evidence_routed_sha256"] == record["routed_sha256"]
    assert profile["image_sha256"] == record["bitstream_sha256"]
    assert profile["compressed_sha256"] == record["compressed_bitstream_sha256"]

    regression = json.loads(
        (ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8")
    )
    packed = next(
        row for row in regression["artifacts"]
        if row["routed"] == "qualification/mcu_ahb_public16_exact_map_routed.json"
    )
    assert profile["routed_sha256"] == packed["routed_sha256"]
    assert profile["image_sha256"] == packed["bitstream_sha256"]


def test_public32_profile_hashes_bind_the_silicon_evidence():
    profile = json.loads(
        (ROOT / "agamemnon" / "sdk" / "qualified_fabric_profiles.json").read_text(
            encoding="utf-8"
        )
    )["profiles"]["l48-public32-exact-map-2026-08-15"]
    record = json.loads(
        (ROOT / "qualification" / "mcu_ahb_public32_evidence.jsonl").read_text(
            encoding="utf-8"
        ).strip()
    )
    source = (ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
              "logic" / "top.v")
    routed = (ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
              "logic" / "public32_exact_map_L48_routed.json")
    assert profile["source_sha256"] == project._sha256_file(source)
    assert profile["source_sha256"] == record["source_sha256"]
    assert profile["routed_sha256"] == project._sha256_file(routed)
    assert profile["evidence_routed_sha256"] == record["routed_sha256"]
    assert profile["image_sha256"] == record["bitstream_sha256"]
    assert profile["compressed_sha256"] == record["compressed_bitstream_sha256"]

    regression = json.loads(
        (ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8")
    )
    packed = next(row for row in regression["artifacts"]
                  if row["routed"] ==
                  "qualification/mcu_ahb_public32_exact_map_routed.json")
    assert profile["routed_sha256"] == packed["routed_sha256"]
    assert profile["image_sha256"] == packed["bitstream_sha256"]


def test_qualified_serv_profile_binds_the_retained_pack_gate():
    profile = json.loads(
        (ROOT / "agamemnon" / "sdk" / "qualified_fabric_profiles.json").read_text(
            encoding="utf-8"
        )
    )["profiles"]["l48-serv-blinky-2026-07-15"]
    regression = json.loads(
        (ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8")
    )
    record = next(
        row for row in regression["artifacts"]
        if row["routed"] == "qualification/serv_blinky_L48_routed.json"
    )
    assert profile["routed_sha256"] == record["routed_sha256"]
    assert profile["image_sha256"] == record["bitstream_sha256"]
    assert profile["pack_environment"] == {
        "AGAMEMNON_DEVICE": "AGRV2KL48",
        **record["environment"],
    }


def test_all_maintained_template_payloads_exist():
    root = ROOT / "agamemnon" / "templates"
    for name in project.TEMPLATE_NAMES:
        payload = project.TEMPLATE_ALIASES.get(name, name)
        assert (root / payload).is_dir(), name
        assert (root / payload / "agamemnon.toml").is_file(), name


def test_source_build_template_stays_inside_release_claims():
    root = ROOT / "agamemnon" / "templates"
    assert "fpga-blink" in project.TEMPLATE_NAMES
    assert not any(path.is_file() for path in (root / "fpga-blink").rglob("*"))
    pcf = (root / "fpga-io" / "board.pcf").read_text(encoding="utf-8").splitlines()
    assert pcf == [
        "set_io led[0] PIN_25", "set_io led[1] PIN_26",
        "set_io led[2] PIN_27", "set_io led[3] PIN_28",
    ]
    source = (root / "fpga-io" / "logic" / "top.v").read_text(encoding="utf-8")
    assert source.count("(* keep *) LUT") == 4
    assert "always" not in source
    assert "reg " not in source


def test_fpga_blink_compatibility_alias_uses_safe_payload(tmp_path, capsys):
    destination = tmp_path / "legacy-name"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="fpga-blink", board="ag32vf303-l48"
    ))
    captured = capsys.readouterr()
    assert "deprecated" in captured.err
    assert (destination / "logic" / "top.v").read_text(encoding="utf-8") == (
        ROOT / "agamemnon" / "templates" / "fpga-io" / "logic" / "top.v"
    ).read_text(encoding="utf-8")


def test_project_frequency_can_be_overridden_from_the_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("AGAMEMNON_DEVICE", "restore-after-test")
    monkeypatch.setenv("AGAMEMNON_HSE", "7")
    destination = tmp_path / "hello"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="fpga-io", board="ag32vf303-l48"
    ))
    args = SimpleNamespace(freq=25)
    loaded = project.Project.load(destination)

    assert project.apply_fabric_config(args, loaded)
    assert args.freq == 25


def test_synthesis_scripts_accept_explicit_top():
    for name in ("synth_pads.tcl", "synth_generic.tcl"):
        text = (ROOT / "agamemnon" / "synth" / name).read_text(encoding="utf-8")
        assert "hierarchy -check -top $TOP" in text


def test_synthesis_scripts_resolve_packaged_companion_files_from_the_script():
    for name in ("synth_pads.tcl", "synth_generic.tcl"):
        text = (ROOT / "agamemnon" / "synth" / name).read_text(encoding="utf-8")
        assert "set SCRIPT_DIR [file dirname [file normalize [info script]]]" in text
        assert "$argv0" not in text


def test_mcu_bridge_policy_fails_before_external_build_tools(tmp_path):
    source = tmp_path / "top.v"
    source.write_text("module top; endmodule\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, "-m", "agamemnon.cli", "build", str(source),
            "--uarch", "--mcu",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "option:AGAMEMNON_MCU_ENTRY" in output
    assert "preflight failed before synthesis" in output
    assert "[build] synth:" not in output


@pytest.mark.parametrize("device", ["AGRV2KQ32", "AGRV2KL64", "AGRV2KL100"])
def test_unqualified_package_pad_free_build_passes_preflight(tmp_path, device):
    """T25: per-part legality -- a pad-free build is package-independent.

    This used to blanket-reject any non-L48 device before synthesis (the T21
    finding), regardless of surface. The AG32 family shares one AGRV2K
    fabric, so a build that never activates a physical/electrical option
    (no --pcf here) must now clear the claim-policy preflight and reach
    synthesis on every package; only the physical/electrical claim itself
    stays AGRV2KL48-only (see test_unqualified_package_with_pcf_still_fails_closed).
    Tool absence past that point (this desk machine has no yosys) is a
    separate, expected failure -- not the one this test is about.
    """
    source = tmp_path / "top.v"
    source.write_text("module top; endmodule\n", encoding="utf-8")
    env = dict(os.environ, AGAMEMNON_DEVICE=device)
    result = subprocess.run(
        [
            sys.executable, "-m", "agamemnon.cli", "build", str(source),
            "--uarch",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    output = result.stdout + result.stderr
    assert "strict emission is qualified only for AGRV2KL48" not in output
    assert "preflight failed before synthesis" not in output
    assert "[build] synth:" in output


@pytest.mark.parametrize("device", ["AGRV2KQ32", "AGRV2KL64", "AGRV2KL100"])
def test_unqualified_package_with_pcf_still_fails_closed(tmp_path, device):
    """The physical/electrical claim (here: any --pcf build) never auto-transfers off L48."""
    source = tmp_path / "top.v"
    source.write_text("module top (output led); assign led = 1'b0; endmodule\n", encoding="utf-8")
    pcf = tmp_path / "top.pcf"
    pcf.write_text("set_io led PIN_25\n", encoding="utf-8")
    env = dict(os.environ, AGAMEMNON_DEVICE=device)
    result = subprocess.run(
        [
            sys.executable, "-m", "agamemnon.cli", "build", str(source),
            "--uarch", "--pcf", str(pcf),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "strict emission of a physical/electrical surface" in output
    assert "qualified only for AGRV2KL48" in output
    assert "preflight failed before synthesis" in output
    assert "[build] synth:" not in output


def test_project_flash_layout_records_hashes_and_rejects_overlap(tmp_path):
    root = tmp_path / "layout"
    (root / "build").mkdir(parents=True)
    (root / "build" / "mcu.bin").write_bytes(b"mcu")
    (root / "build" / "fabric.bin").write_bytes(b"fabric")
    data = {
        "project": {"name": "layout", "board": "ag32vf303-l48"},
        "flash": {"mcu_address": 0x80000000, "fabric_address": 0x80001000},
    }
    loaded = project.Project(root, data)
    output = project.write_flash_plan(
        loaded, str(root / "build" / "mcu.bin"), str(root / "build" / "fabric.bin")
    )
    text = Path(output).read_text(encoding="utf-8")
    assert '"address": 2147483648' in text
    assert '"sha256"' in text
    # The "file" field is a portable manifest value, not a native display path:
    # it must use forward slashes on every host OS so the same project produces
    # a byte-identical flash-layout.json on Windows and POSIX (regression --
    # this used to be `str(Path(...).relative_to(...))`, which emitted
    # backslashes on Windows for any nested output path).
    record = json.loads(text)
    assert {row["file"] for row in record["regions"]} == {
        "build/mcu.bin", "build/fabric.bin"}
    assert "\\" not in text

    loaded.flash["fabric_address"] = 0x80000002
    try:
        project.write_flash_plan(
            loaded, str(root / "build" / "mcu.bin"), str(root / "build" / "fabric.bin")
        )
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("overlapping flash regions were accepted")
