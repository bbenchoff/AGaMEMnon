"""Assemble a relocatable AGaMEMnon release bundle from pinned tool trees."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

try:
    from .openocd_audit import audit as audit_openocd
except ImportError:  # Direct execution: python tools/bundle/build_bundle.py
    from openocd_audit import audit as audit_openocd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha256_file(path, chunk_size=1024 * 1024):
    """Hash a file without making archive-sized memory allocations."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy(source, destination):
    source = Path(source).resolve()
    if not source.exists():
        raise SystemExit(f"bundle input does not exist: {source}")
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def validate_openocd_arguments(openocd, openocd_source):
    """Accept no OpenOCD, or a binary paired with its corresponding source."""
    if bool(openocd) != bool(openocd_source):
        raise ValueError("--openocd and --openocd-source must be supplied together")
    return bool(openocd)


def _require_one(root, relative):
    """Return a host executable, accepting the Windows suffix on either host."""
    root = Path(root).resolve()
    candidates = [root / relative, root / f"{relative}.exe"]
    matches = [path for path in candidates if path.is_file()]
    if len(matches) != 1:
        rendered = " or ".join(str(path.relative_to(root)) for path in candidates)
        raise ValueError(f"missing required bundled tool: {rendered}")
    return matches[0]


def validate_release_inputs(oss, nextpnr, toolchain, manifest):
    """Reject incomplete or incorrectly labelled pinned build-tool inputs."""
    oss = Path(oss).resolve()
    nextpnr = Path(nextpnr).resolve()
    toolchain = Path(toolchain).resolve()
    if not oss.is_dir():
        raise ValueError(f"OSS CAD Suite root is not a directory: {oss}")
    _require_one(oss, "bin/yosys")
    if not nextpnr.is_file():
        raise ValueError(f"nextpnr executable is not a file: {nextpnr}")
    if not toolchain.is_dir():
        raise ValueError(f"RISC-V toolchain root is not a directory: {toolchain}")
    _require_one(toolchain, "bin/riscv-none-elf-gcc")
    _require_one(toolchain, "bin/riscv-none-elf-objcopy")

    version = manifest["pins"]["riscv_toolchain"]["version"]
    if version.endswith("-1"):
        version = version[:-2]
    gcc_licenses = toolchain / "distro-info" / "licenses" / f"gcc-{version}"
    required_licenses = ("COPYING", "COPYING.RUNTIME")
    missing = [
        name for name in required_licenses
        if not (gcc_licenses / name).is_file()
    ]
    if missing:
        raise ValueError(
            "pinned xPack GCC license tree is incomplete: "
            + ", ".join(str(gcc_licenses / name) for name in missing)
        )


def validate_dependency_wheels(wheels, manifest):
    """Require exactly the universal Python wheels pinned for offline installs."""
    supplied = {Path(path).name: Path(path).resolve() for path in wheels}
    pins = manifest["pins"].get("python_dependencies", {})
    expected = {pin["asset"] for pin in pins.values()}
    missing = sorted(expected - set(supplied))
    unexpected = sorted(set(supplied) - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError("; ".join(details))
    for pin in pins.values():
        path = supplied[pin["asset"]]
        if not path.is_file():
            raise ValueError(f"dependency wheel is not a file: {path}")
        digest = sha256_file(path)
        if digest != pin["sha256"]:
            raise ValueError(
                f"{path.name} SHA-256 mismatch: expected {pin['sha256']}, "
                f"got {digest}"
            )


def validate_nextpnr_runtime(runtime):
    """Require a staged DLL closure with its corresponding license texts."""
    if not runtime:
        return
    runtime = Path(runtime).resolve()
    if not runtime.is_dir():
        raise ValueError(f"nextpnr runtime is not a directory: {runtime}")
    dlls = list(runtime.glob("*.dll"))
    licenses = list((runtime / "licenses").rglob("*"))
    if not dlls:
        raise ValueError("nextpnr runtime contains no DLLs")
    if not any(path.is_file() for path in licenses):
        raise ValueError("nextpnr runtime contains no license texts")


def validate_nextpnr_license(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"nextpnr license is not a file: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "Permission to use, copy, modify" not in text:
        raise ValueError(f"nextpnr ISC grant not found in {path}")


def artifact_record(root, relative):
    """Hash one bundled file/tree without relying on archive metadata."""
    root = Path(root)
    path = root / relative
    files = [path] if path.is_file() else sorted(
        item for item in path.rglob("*") if item.is_file()
    )
    aggregate = hashlib.sha256()
    total = 0
    for item in files:
        name = item.relative_to(root).as_posix()
        digest = sha256_file(item)
        size = item.stat().st_size
        aggregate.update(name.encode("utf-8") + b"\0")
        aggregate.update(digest.encode("ascii") + b"\0")
        total += size
    return {
        "path": Path(relative).as_posix(),
        "files": len(files),
        "bytes": total,
        "tree_sha256": aggregate.hexdigest(),
    }


def write_component_inventory(
    output, manifest, has_openocd, runtime_present, wheel, nextpnr
):
    pins = manifest["pins"]
    definitions = manifest["components"]
    records = [
        {
            "id": "agamemnon",
            "version": manifest["bundle_version"],
            **definitions["agamemnon"],
            "artifact": artifact_record(output, f"packages/{Path(wheel).name}"),
        },
        {
            "id": "fabric_default",
            **definitions["fabric_default"],
            "contained_in": "agamemnon wheel",
        },
        {
            "id": "oss_cad_suite",
            "version": pins["oss_cad_suite"]["version"],
            "repository": pins["oss_cad_suite"]["repository"],
            **definitions["oss_cad_suite"],
            "artifact": artifact_record(output, "tools/oss-cad-suite"),
        },
        {
            "id": "nextpnr",
            "commit": pins["nextpnr"]["commit"],
            "repository": pins["nextpnr"]["repository"],
            **definitions["nextpnr"],
            "binary_artifact": artifact_record(
                output, f"tools/nextpnr/{Path(nextpnr).name}"
            ),
            "license_artifact": artifact_record(
                output, "tools/nextpnr/COPYING"
            ),
        },
        {
            "id": "riscv_gnu_toolchain",
            "version": pins["riscv_toolchain"]["version"],
            "tag": pins["riscv_toolchain"]["tag"],
            "repository": pins["riscv_toolchain"]["repository"],
            **definitions["riscv_gnu_toolchain"],
            "artifact": artifact_record(output, "tools/riscv"),
        },
    ]
    for component_id, pin in manifest["pins"].get("python_dependencies", {}).items():
        records.append({
            "id": component_id,
            "version": pin["version"],
            **definitions[component_id],
            "artifact": artifact_record(output, f"packages/{pin['asset']}"),
        })
    if runtime_present:
        records.append({
            "id": "nextpnr_runtime",
            "license": "NOASSERTION",
            "notice": "Runtime libraries retain their individual upstream licenses.",
            "artifact": artifact_record(output, "tools/nextpnr/runtime"),
        })
    if has_openocd:
        records.append({
            "id": "openocd",
            "commit": pins["openocd"]["agamemnon_patched_commit"],
            **definitions["openocd"],
            "binary_artifact": artifact_record(output, "tools/openocd"),
            "corresponding_source": artifact_record(output, "sources/openocd"),
        })
    document = {
        "schema": 1,
        "bundle_version": manifest["bundle_version"],
        "generated_by": "tools/bundle/build_bundle.py",
        "scope": "Top-level release inputs; nested upstream components retain their own notices.",
        "components": records,
    }
    (Path(output) / "COMPONENTS.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


def validate_wheel(path, manifest):
    """Reject a source-tree-only or version-mismatched release wheel."""
    required = {
        "agamemnon/chipdb/fabric_default.bin",
        "agamemnon/engine/mesh_resolver_table.json",
        "agamemnon/engine/pips_bram_pll.csv",
        "agamemnon/archdec_cfg/alta_tile_agr_cfg.csv",
        "agamemnon/sdk/support_matrix.json",
    }
    research_only = {
        "agamemnon/chipdb/pip_usage.csv",
        "agamemnon/chipdb/rrg_rmux_imux_full.csv",
    }
    try:
        with zipfile.ZipFile(path) as wheel:
            names = set(wheel.namelist())
            missing = sorted(required - names)
            if missing:
                raise ValueError(
                    "wheel is missing required runtime data: " + ", ".join(missing)
                )
            unexpected = sorted(research_only & names)
            if unexpected:
                raise ValueError(
                    "wheel contains research-only chip databases: "
                    + ", ".join(unexpected)
                )
            baseline = wheel.read("agamemnon/chipdb/fabric_default.bin")
            expected = manifest["components"]["fabric_default"]
            if len(baseline) != expected["bytes"]:
                raise ValueError("wheel fabric_default.bin size does not match manifest")
            if hashlib.sha256(baseline).hexdigest() != expected["sha256"]:
                raise ValueError("wheel fabric_default.bin hash does not match manifest")
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ValueError("wheel must contain exactly one dist-info/METADATA")
            metadata = wheel.read(metadata_names[0]).decode("utf-8", errors="replace")
            version_line = f"Version: {manifest['bundle_version']}"
            if version_line not in metadata.splitlines():
                raise ValueError(
                    f"wheel metadata does not contain {version_line!r}"
                )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"invalid AGaMEMnon wheel: {path}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--oss", required=True, help="OSS CAD Suite root")
    parser.add_argument("--nextpnr", required=True, help="AGRV2K nextpnr executable")
    parser.add_argument(
        "--nextpnr-license", required=True,
        help="COPYING from the exact pinned nextpnr source tree",
    )
    parser.add_argument("--nextpnr-runtime", help="matching runtime DLL directory")
    parser.add_argument("--toolchain", required=True, help="RISC-V toolchain root")
    parser.add_argument(
        "--openocd",
        help="optional compatible OpenOCD root; omit for a build-only SDK",
    )
    parser.add_argument(
        "--openocd-source",
        help="unpacked corresponding GPL source for the exact compatible OpenOCD build",
    )
    parser.add_argument("--wheel", required=True, help="AGaMEMnon wheel")
    parser.add_argument(
        "--dependency-wheel", action="append", default=[],
        help="wheel needed for offline installation (repeatable; e.g. tomli on Python <3.11)",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(HERE / "manifest.json", encoding="utf-8") as source:
        manifest = json.load(source)
    try:
        validate_release_inputs(
            args.oss, args.nextpnr, args.toolchain, manifest
        )
        validate_dependency_wheels(args.dependency_wheel, manifest)
        validate_nextpnr_runtime(args.nextpnr_runtime)
        validate_nextpnr_license(args.nextpnr_license)
    except ValueError as exc:
        raise SystemExit(f"Build-tool bundle preflight failed: {exc}") from exc
    try:
        validate_wheel(args.wheel, manifest)
    except ValueError as exc:
        raise SystemExit(f"AGaMEMnon wheel preflight failed: {exc}") from exc

    try:
        has_openocd = validate_openocd_arguments(args.openocd, args.openocd_source)
        openocd_source = None
        if has_openocd:
            _, openocd_source = audit_openocd(args.openocd, args.openocd_source)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"OpenOCD bundle preflight failed: {exc}") from exc

    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy(args.oss, output / "tools" / "oss-cad-suite")
    copy(args.nextpnr, output / "tools" / "nextpnr" / Path(args.nextpnr).name)
    copy(args.nextpnr_license, output / "tools" / "nextpnr" / "COPYING")
    if args.nextpnr_runtime:
        copy(args.nextpnr_runtime, output / "tools" / "nextpnr" / "runtime")
    copy(args.toolchain, output / "tools" / "riscv")
    if has_openocd:
        copy(args.openocd, output / "tools" / "openocd")
        copy(openocd_source, output / "sources" / "openocd")
    copy(args.wheel, output / "packages" / Path(args.wheel).name)
    for wheel in args.dependency_wheel:
        copy(wheel, output / "packages" / Path(wheel).name)
    copy(HERE / "manifest.json", output / "manifest.json")
    copy(HERE / "README.md", output / "BUILDING.md")
    copy(HERE / "python-requirements.txt", output / "python-requirements.txt")
    copy(ROOT / "LICENSE", output / "LICENSE")
    copy(ROOT / "NOTICE.md", output / "NOTICE.md")
    copy(ROOT / "docs" / "INSTALLATION.md", output / "INSTALLATION.md")
    copy(HERE / "smoke_archive.py", output / "smoke" / "smoke_archive.py")
    copy(
        ROOT / "tests" / "fixtures" / "counter_ahb_routed.json",
        output / "smoke" / "counter_ahb_routed.json",
    )

    powershell_activation = (
        "$Root = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
        "$Venv = Join-Path $Root '.venv/Scripts'\n"
        "if (Test-Path (Join-Path $Venv 'python.exe')) { $env:PATH = $Venv + ';' + $env:PATH }\n"
        "$env:AGAMEMNON_OSS = Join-Path $Root 'tools/oss-cad-suite'\n"
        "$env:AGAMEMNON_UARCH_NEXTPNR = Join-Path $Root 'tools/nextpnr/nextpnr-generic.exe'\n"
        "$env:PATH = (Join-Path $Root 'tools/riscv/bin') + ';' + $env:PATH\n"
    )
    shell_activation = (
        "SCRIPT=${BASH_SOURCE:-$0}\n"
        "ROOT=${AGAMEMNON_SDK_ROOT:-$(CDPATH= cd -- \"$(dirname -- \"$SCRIPT\")\" && pwd)}\n"
        "[ ! -x \"$ROOT/.venv/bin/python\" ] || export PATH=\"$ROOT/.venv/bin:$PATH\"\n"
        "export AGAMEMNON_OSS=\"$ROOT/tools/oss-cad-suite\"\n"
        "export AGAMEMNON_UARCH_NEXTPNR=\"$ROOT/tools/nextpnr/nextpnr-generic\"\n"
        "export PATH=\"$ROOT/tools/riscv/bin:$PATH\"\n"
    )
    if args.nextpnr_runtime:
        powershell_activation += (
            "$env:AGAMEMNON_UARCH_NEXTPNR_RUNTIME = "
            "Join-Path $Root 'tools/nextpnr/runtime'\n"
        )
        shell_activation += (
            "export AGAMEMNON_UARCH_NEXTPNR_RUNTIME="
            "\"$ROOT/tools/nextpnr/runtime\"\n"
        )
    if has_openocd:
        powershell_activation += (
            "$env:AGAMEMNON_OPENOCD = Join-Path $Root 'tools/openocd/bin/openocd.exe'\n"
            "$env:AGAMEMNON_OOCD_SCRIPTS = Join-Path $Root 'tools/openocd/share/openocd/scripts'\n"
        )
        shell_activation += (
            "export AGAMEMNON_OPENOCD=\"$ROOT/tools/openocd/bin/openocd\"\n"
            "export AGAMEMNON_OOCD_SCRIPTS=\"$ROOT/tools/openocd/share/openocd/scripts\"\n"
        )
    (output / "activate.ps1").write_text(powershell_activation, encoding="utf-8")
    (output / "activate.sh").write_text(shell_activation, encoding="utf-8")
    (output / "BUNDLE_VERSION").write_text(manifest["bundle_version"] + "\n", encoding="ascii")
    write_component_inventory(
        output,
        manifest,
        has_openocd,
        bool(args.nextpnr_runtime),
        args.wheel,
        args.nextpnr,
    )
    archive = shutil.make_archive(str(output), "zip" if sys.platform == "win32" else "gztar", output.parent, output.name)
    digest = sha256_file(archive)
    Path(archive + ".sha256").write_text(f"{digest}  {Path(archive).name}\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
