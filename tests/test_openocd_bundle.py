from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile

import pytest

from agamemnon import tool_install
from tools.bundle import build_bundle, fetch_tools
from tools.bundle.build_bundle import (
    make_reproducible_archive,
    sha256_file,
    validate_openocd_arguments,
    validate_dependency_wheels,
    validate_nextpnr_license,
    validate_nextpnr_runtime,
    validate_release_inputs,
    validate_wheel,
)
from tools.bundle.smoke_archive import extract_archive, verify_sidecar
from tools.bundle.verify_release_set import verify as verify_release_set
from tools.bundle.fetch_tools import extract as extract_tool_archive
from tools.bundle.openocd_audit import classify_dap_probe, validate_corresponding_source
from agamemnon.tool_shim import stage_windows_directory, stage_windows_executable
from tools.openocd import release as openocd_release
from tools.openocd.release import make_sbom, manifest, patch_hashes


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("archive_format", ["zip", "gztar"])
def test_release_archives_are_metadata_reproducible(tmp_path, archive_format):
    roots = []
    for parent_name, mtime in (("first", 1_700_000_000), ("second", 1_800_000_000)):
        root = tmp_path / parent_name / "agamemnon-sdk-fixture"
        (root / "bin").mkdir(parents=True)
        executable = root / "bin" / "tool"
        executable.write_bytes(b"tool bytes\n")
        executable.chmod(0o755)
        (root / "README").write_bytes(b"stable payload\n")
        for path in (root, root / "bin", executable, root / "README"):
            path.chmod(0o755 if path.is_dir() or path == executable else 0o644)
            # Distinct source mtimes must not affect the resulting archive.
            os.utime(path, (mtime, mtime))
        roots.append(root)

    archives = [
        make_reproducible_archive(root, archive_format, 946684800)
        for root in roots
    ]
    assert sha256_file(archives[0]) == sha256_file(archives[1])

    if archive_format == "zip":
        with zipfile.ZipFile(archives[0]) as bundle:
            assert {entry.date_time for entry in bundle.infolist()} == {
                (2000, 1, 1, 0, 0, 0)
            }
    else:
        with tarfile.open(archives[0], "r:gz") as bundle:
            assert {entry.mtime for entry in bundle.getmembers()} == {946684800}
            assert {entry.uid for entry in bundle.getmembers()} == {0}


def _write_fixture_wheel(path, version="0.3.0", omit=()):
    files = {
        "agamemnon/chipdb/fabric_default.bin":
            (ROOT / "agamemnon/chipdb/fabric_default.bin").read_bytes(),
        "agamemnon/engine/mesh_resolver_table.json": b"{}",
        "agamemnon/engine/pips_bram_pll.csv": b"fixture\n",
        "agamemnon/archdec_cfg/alta_tile_agr_cfg.csv": b"fixture\n",
        "agamemnon/sdk/support_matrix.json": b"{}",
        f"agamemnon_ag32-{version}.dist-info/METADATA":
            f"Metadata-Version: 2.1\nName: agamemnon-ag32\nVersion: {version}\n".encode(),
    }
    with zipfile.ZipFile(path, "w") as wheel:
        for name, data in files.items():
            if name not in omit:
                wheel.writestr(name, data)


def _write_fixture_build_tools(root):
    oss = root / "oss"
    toolchain = root / "toolchain"
    nextpnr = root / "nextpnr-generic.exe"
    (oss / "bin").mkdir(parents=True)
    (oss / "bin" / "yosys.exe").write_bytes(b"yosys fixture")
    (toolchain / "bin").mkdir(parents=True)
    (toolchain / "bin" / "riscv-none-elf-gcc.exe").write_bytes(b"gcc fixture")
    (toolchain / "bin" / "riscv-none-elf-objcopy.exe").write_bytes(
        b"objcopy fixture"
    )
    licenses = toolchain / "distro-info" / "licenses" / "gcc-15.2.0"
    licenses.mkdir(parents=True)
    (licenses / "COPYING").write_text("GPL fixture", encoding="utf-8")
    (licenses / "COPYING.RUNTIME").write_text(
        "runtime exception fixture", encoding="utf-8"
    )
    nextpnr.write_bytes(b"nextpnr fixture")
    nextpnr_license = root / "COPYING"
    nextpnr_license.write_text(
        "Permission to use, copy, modify, and/or distribute this software.",
        encoding="utf-8",
    )
    return oss, nextpnr, nextpnr_license, toolchain


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


def test_windows_native_tool_stages_from_non_ascii_path(tmp_path, monkeypatch):
    source = tmp_path / "SDK ü path" / "nextpnr-generic.exe"
    source.parent.mkdir()
    source.write_bytes(b"pinned nextpnr fixture")
    cache = tmp_path / "ascii-cache"
    monkeypatch.setenv("AGAMEMNON_ASCII_TOOL_CACHE", str(cache))

    command = stage_windows_executable([str(source), "--version"], "nt")

    assert command[1:] == ["--version"]
    assert Path(command[0]).read_bytes() == source.read_bytes()
    command[0].encode("ascii")


def test_windows_native_tool_data_stages_from_non_ascii_path(tmp_path, monkeypatch):
    source = tmp_path / "SDK ü path" / "synth"
    source.mkdir(parents=True)
    (source / "prims.v").write_text("module fixture; endmodule\n", encoding="ascii")
    cache = tmp_path / "ascii-cache"
    monkeypatch.setenv("AGAMEMNON_ASCII_TOOL_CACHE", str(cache))

    staged = stage_windows_directory(source, "nt")

    str(staged).encode("ascii")
    assert (staged / "prims.v").read_bytes() == (source / "prims.v").read_bytes()


def test_uarch_cli_preserves_a_literal_windows_tool_path_with_spaces():
    source = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert 'os.name == "nt" and os.path.isfile(unpr)' in source


def test_yosys_tcl_file_is_a_process_argument_not_an_embedded_path():
    source = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert '["yosys", "-q", "-c", synth_tcl, *sources]' in source
    assert 'synth_env["AGAMEMNON_YOSYS_JSON"] = synth_json' in source


def test_windows_sdk_ci_smokes_spaces_and_non_ascii_path():
    workflow = (ROOT / ".github/workflows/sdk-bundle.yml").read_text(encoding="utf-8")
    assert 'TOOLS_ROOT="$RUNNER_TEMP/release-tools"' in workflow
    assert 'OSS="$TOOLS_ROOT/$(python' in workflow
    assert '$toolsRoot = "$env:RUNNER_TEMP/release-tools"' in workflow
    assert '--oss (Join-Path $toolsRoot $tools.oss)' in workflow
    assert '--toolchain (Join-Path $toolsRoot $tools.toolchain)' in workflow
    assert 'needs: [wheel, linux-x64, windows-x64]' in workflow
    assert 'sha256sum -c ./*.sha256' in workflow
    assert 'gh release create "$GITHUB_REF_NAME" release/*' in workflow
    assert '--work "$env:RUNNER_TEMP/SDK smoke ü path"' in workflow


def test_sdk_archive_smoke_covers_both_exact_release_profiles():
    source = (ROOT / "tools/bundle/smoke_archive.py").read_text(encoding="utf-8")
    assert '["new", projects / "fpga", "--template", "fpga-io"]' in source
    assert "fpga-blink" not in source
    assert '"mcu-fpga": "7d6cd01be4799817' in source
    assert '"serv-blinky": "fe7ecca298dc5bd9' in source
    assert 'actual = sha256(fabric)' in source
    assert '"exact_profiles": exact_hashes' in source


def test_release_set_binds_tag_versions_and_one_wheel(tmp_path):
    wheel = tmp_path / "agamemnon_ag32-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "agamemnon_ag32-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: agamemnon-ag32\nVersion: 0.1.0\n",
        )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"bundle_version": "0.1.0"}),
                             encoding="utf-8")

    member = "agamemnon-sdk/packages/" + wheel.name
    windows = tmp_path / "sdk.zip"
    with zipfile.ZipFile(windows, "w") as archive:
        archive.writestr(member, wheel.read_bytes())
    staged = tmp_path / "stage" / member
    staged.parent.mkdir(parents=True)
    staged.write_bytes(wheel.read_bytes())
    linux = tmp_path / "sdk.tar.gz"
    with tarfile.open(linux, "w:gz") as archive:
        archive.add(staged, arcname=member)

    result = verify_release_set(
        "v0.1.0", wheel, linux, windows, pyproject, manifest_path
    )
    assert result["wheel_sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert {item["sha256"] for item in result["embedded"].values()} == {
        result["wheel_sha256"]
    }
    with pytest.raises(ValueError, match="release identity mismatch"):
        verify_release_set(
            "v0.2.0", wheel, linux, windows, pyproject, manifest_path
        )

    with zipfile.ZipFile(windows, "w") as archive:
        archive.writestr(member, b"different wheel")
    with pytest.raises(ValueError, match="published wheel"):
        verify_release_set(
            "v0.1.0", wheel, linux, windows, pyproject, manifest_path
        )


def test_build_only_bundle_omits_openocd_activation(tmp_path, monkeypatch):
    oss, nextpnr, nextpnr_license, toolchain = _write_fixture_build_tools(tmp_path)
    wheel = tmp_path / "agamemnon_ag32-test.whl"
    dependency = tmp_path / "tomli-2.0.1-py3-none-any.whl"
    dependency.write_bytes(b"tomli fixture")
    _write_fixture_wheel(wheel)
    output = tmp_path / "sdk"

    monkeypatch.setattr(
        build_bundle, "validate_dependency_wheels", lambda wheels, manifest: None
    )
    original_read_bytes = Path.read_bytes

    def reject_whole_archive_read(path):
        if str(path).endswith((".zip", ".tar.gz")):
            raise AssertionError("release archives must be hashed as a stream")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_whole_archive_read)
    build_bundle.main([
        "--oss", str(oss),
        "--nextpnr", str(nextpnr),
        "--nextpnr-license", str(nextpnr_license),
        "--toolchain", str(toolchain),
        "--wheel", str(wheel),
        "--dependency-wheel", str(dependency),
        "--output", str(output),
    ])

    powershell = (output / "activate.ps1").read_text(encoding="utf-8")
    shell = (output / "activate.sh").read_text(encoding="utf-8")
    assert ".venv/Scripts" in powershell
    assert ".venv/bin" in shell
    assert "AGAMEMNON_OPENOCD" not in powershell
    assert "AGAMEMNON_OPENOCD" not in shell
    assert "AGAMEMNON_UARCH_NEXTPNR_RUNTIME" not in powershell
    assert "AGAMEMNON_UARCH_NEXTPNR_RUNTIME" not in shell
    archive_suffix = ".zip" if sys.platform == "win32" else ".tar.gz"
    archive = Path(str(output) + archive_suffix)
    assert archive.is_file()
    assert Path(str(archive) + ".sha256").is_file()
    assert verify_sidecar(archive) == sha256_file(archive)
    assert (output / "LICENSE").is_file()
    assert (output / "NOTICE.md").is_file()
    assert (output / "BUILDING.md").is_file()
    assert (output / "python-requirements.txt").is_file()
    assert (output / "smoke" / "smoke_archive.py").is_file()
    inventory = json.loads((output / "COMPONENTS.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in inventory["components"]} >= {
        "agamemnon", "fabric_default", "oss_cad_suite", "nextpnr",
        "riscv_gnu_toolchain", "tomli",
    }
    baseline = next(
        item for item in inventory["components"] if item["id"] == "fabric_default"
    )
    assert baseline["license"] == "NOASSERTION"
    assert baseline["sha256"] == hashlib.sha256(
        (ROOT / "agamemnon/chipdb/fabric_default.bin").read_bytes()
    ).hexdigest()
    nextpnr_component = next(
        item for item in inventory["components"] if item["id"] == "nextpnr"
    )
    assert nextpnr_component["license_artifact"]["path"] == "tools/nextpnr/COPYING"


def test_bundle_preflight_rejects_unpinned_or_unlicensed_toolchain(tmp_path):
    manifest = json.loads(
        (ROOT / "tools/bundle/manifest.json").read_text(encoding="utf-8")
    )
    oss, nextpnr, _, toolchain = _write_fixture_build_tools(tmp_path)
    validate_release_inputs(oss, nextpnr, toolchain, manifest)

    (toolchain / "distro-info/licenses/gcc-15.2.0/COPYING.RUNTIME").unlink()
    with pytest.raises(ValueError, match="license tree is incomplete"):
        validate_release_inputs(oss, nextpnr, toolchain, manifest)


def test_bundle_requires_exact_pinned_offline_python_dependency(tmp_path):
    manifest = json.loads(
        (ROOT / "tools/bundle/manifest.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError, match="missing tomli-2.0.1"):
        validate_dependency_wheels([], manifest)
    wrong = tmp_path / "tomli-2.0.1-py3-none-any.whl"
    wrong.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_dependency_wheels([wrong], manifest)


def test_windows_nextpnr_runtime_requires_dlls_and_license_texts(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with pytest.raises(ValueError, match="no DLLs"):
        validate_nextpnr_runtime(runtime)
    (runtime / "libstdc++-6.dll").write_bytes(b"fixture")
    with pytest.raises(ValueError, match="no license texts"):
        validate_nextpnr_runtime(runtime)
    licenses = runtime / "licenses" / "gcc-libs"
    licenses.mkdir(parents=True)
    (licenses / "COPYING.RUNTIME").write_text("fixture", encoding="utf-8")
    validate_nextpnr_runtime(runtime)


def test_nextpnr_binary_requires_its_isc_notice(tmp_path):
    notice = tmp_path / "COPYING"
    notice.write_text("not a license", encoding="utf-8")
    with pytest.raises(ValueError, match="ISC grant not found"):
        validate_nextpnr_license(notice)
    notice.write_text(
        "Permission to use, copy, modify, and/or distribute this software.",
        encoding="utf-8",
    )
    validate_nextpnr_license(notice)


def test_bundle_wheel_preflight_checks_version_runtime_data_and_baseline(tmp_path):
    manifest = json.loads(
        (ROOT / "tools/bundle/manifest.json").read_text(encoding="utf-8")
    )
    valid = tmp_path / "valid.whl"
    _write_fixture_wheel(valid)
    validate_wheel(valid, manifest)

    missing = tmp_path / "missing.whl"
    _write_fixture_wheel(missing, omit={"agamemnon/engine/pips_bram_pll.csv"})
    with pytest.raises(ValueError, match="missing required runtime data"):
        validate_wheel(missing, manifest)

    research = tmp_path / "research.whl"
    _write_fixture_wheel(research)
    with zipfile.ZipFile(research, "a") as wheel:
        wheel.writestr("agamemnon/chipdb/pip_usage.csv", b"research only")
    with pytest.raises(ValueError, match="research-only chip databases"):
        validate_wheel(research, manifest)

    wrong_version = tmp_path / "wrong-version.whl"
    _write_fixture_wheel(wrong_version, version="9.9.9")
    with pytest.raises(ValueError, match="Version: 0.3.0"):
        validate_wheel(wrong_version, manifest)


def test_archive_smoke_checksum_and_extraction_reject_traversal(tmp_path):
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("agamemnon-sdk/BUNDLE_VERSION", "0.1.0\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    assert verify_sidecar(archive) == digest
    extract_archive(archive, tmp_path / "safe")
    assert (tmp_path / "safe/agamemnon-sdk/BUNDLE_VERSION").is_file()

    malicious = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as output:
        output.writestr("../escaped", "no")
    with pytest.raises(RuntimeError, match="escapes extraction root"):
        extract_archive(malicious, tmp_path / "unsafe")
    with pytest.raises(RuntimeError, match="escapes extraction root"):
        extract_tool_archive(malicious, tmp_path / "unsafe-tools")


def test_sdk_manifest_pins_real_windows_and_linux_tool_assets():
    data = json.loads(
        (ROOT / "tools/bundle/manifest.json").read_text(encoding="utf-8")
    )
    for pin_name in ("oss_cad_suite", "riscv_toolchain"):
        pin = data["pins"][pin_name]
        assert set(pin["assets"]) == {"windows-x64", "linux-x64"}
        for asset in pin["assets"].values():
            assert len(asset["sha256"]) == 64
            assert asset["name"]
    assert data["pins"]["agm_riscv_toolchain_windows"]["redistribute"] is False


def test_nextpnr_release_build_fails_instead_of_floating_the_pin():
    script = (
        ROOT / "agamemnon/engine/uarch/agrv2k/build.sh"
    ).read_text(encoding="utf-8")
    assert 'checkout --detach "$NEXTPNR_PIN"' in script
    assert "staying on default branch" not in script


def test_sdk_installers_verify_and_install_the_wheel_offline():
    powershell = (ROOT / "tools/install.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "tools/install.sh").read_text(encoding="utf-8")
    for script in (powershell, shell):
        assert "sha256" in script.lower()
        assert "--no-index" in script
        assert "doctor --no-hardware" in script
        assert ".venv" in script


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
    assert data["build_environment"]["linux"]["reference_packages"] == ["git"]
    assert data["build_environment"]["windows"]["reference_packages"] == ["git"]


def test_openocd_environment_allows_fetch_tool_drift_but_not_missing_tools(
        monkeypatch, capsys):
    data = {
        "build_environment": {
            "linux": {
                "packages": {"git": "old-git", "gcc": "locked-gcc"},
                "reference_packages": ["git"],
            }
        }
    }
    actual = {"git": "new-git", "gcc": "locked-gcc"}
    monkeypatch.setattr(openocd_release, "manifest", lambda: data)
    monkeypatch.setattr(
        openocd_release,
        "run",
        lambda args, **kwargs: actual[args[-1]],
    )
    openocd_release.verify_environment("linux")
    assert "git: new-git (reference old-git)" in capsys.readouterr().out

    actual["git"] = "not installed"
    with pytest.raises(SystemExit, match="git: not installed"):
        openocd_release.verify_environment("linux")


def test_openocd_patches_are_forced_to_lf_on_windows_checkouts():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.patch text eol=lf" in attributes
    for patch in (ROOT / "tools" / "openocd" / "patches").glob("*.patch"):
        assert b"\r\n" not in patch.read_bytes()


def test_fetch_tools_can_select_only_yosys(tmp_path, monkeypatch):
    downloaded = []

    def fake_download(url, output, expected):
        output = Path(output)
        output.write_bytes(url.encode("utf-8"))
        downloaded.append(output.name)
        return output

    monkeypatch.setattr(fetch_tools, "download", fake_download)
    monkeypatch.setattr(fetch_tools, "extract", lambda archive, destination: None)
    monkeypatch.setattr(
        fetch_tools,
        "_find_root",
        lambda root, relative: Path(root) / "fixture-root",
    )
    result = tmp_path / "tools.json"
    fetch_tools.main([
        "--platform", "linux-x64",
        "--component", "oss_cad_suite",
        "--output", str(tmp_path / "output"),
        "--cache", str(tmp_path / "cache"),
        "--json-output", str(result),
    ])
    parsed = json.loads(result.read_text(encoding="utf-8"))
    assert "oss" in parsed
    assert "toolchain" not in parsed
    assert list(parsed["archives"]) == ["oss_cad_suite"]
    assert parsed["path_policy"] == {
        "portable": True,
        "archives": "basename_only",
        "tool_roots": "relative_to_output",
    }
    assert parsed["archives"]["oss_cad_suite"]["path"] == downloaded[0]
    assert not Path(parsed["archives"]["oss_cad_suite"]["path"]).is_absolute()
    assert parsed["oss"] == "extracted/oss_cad_suite/fixture-root"
    assert not Path(parsed["oss"]).is_absolute()
    assert str(tmp_path) not in result.read_text(encoding="utf-8")
    assert len(downloaded) == 1


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
    assert '$ErrorActionPreference = "Continue"' in workflow
    assert "$ErrorActionPreference = $previousErrorActionPreference" in workflow
    assert "$probeExitCode = $LASTEXITCODE" in workflow
    assert 'if ($probeExitCode -eq 0)' in workflow
    assert 'if (($output -join "`n") -notmatch "definitely_missing")' in workflow
    assert "          exit 0\n" in workflow

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
