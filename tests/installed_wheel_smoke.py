#!/usr/bin/env python3
"""Smoke-test an installed AGaMEMnon wheel from outside the source tree."""

import os
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

try:
    import tomllib
except ImportError:  # Python 3.8-3.10 use the project's declared dependency.
    import tomli as tomllib


def fail(message):
    raise SystemExit(message)


def declared_package_data(repository):
    """Expand setuptools package-data from its single pyproject source."""
    config = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    declarations = config["tool"]["setuptools"]["package-data"]
    expected = set()
    for package, patterns in declarations.items():
        package_root = repository / Path(*package.split("."))
        if not package_root.is_dir():
            fail(f"package-data declaration has no package directory: {package}")
        for pattern in patterns:
            expected.update(
                path.relative_to(repository).as_posix()
                for path in package_root.glob(pattern)
                if path.is_file()
            )
    if not expected:
        fail("pyproject package-data declaration expanded to no files")
    return expected


def main():
    if len(sys.argv) != 3:
        fail("usage: installed_wheel_smoke.py WHEEL ROUTED_FIXTURE")

    wheel = Path(sys.argv[1]).resolve()
    routed = Path(sys.argv[2]).resolve()
    repository = Path(__file__).resolve().parents[1]
    source_package = repository / "agamemnon"

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    required = declared_package_data(repository)
    missing = sorted(required - names)
    if missing:
        fail("wheel is missing runtime files: " + ", ".join(missing))

    research_only = {
        "agamemnon/chipdb/pip_usage.csv",
        "agamemnon/chipdb/rrg_rmux_imux_full.csv",
    }
    unexpected = sorted(research_only & names)
    if unexpected:
        fail("wheel contains source-checkout-only research tables: " + ", ".join(unexpected))
    pickles = sorted(name for name in names if name.endswith(".pkl"))
    if pickles:
        fail("wheel contains executable pickle data: " + ", ".join(pickles))

    generated_markers = ("/devdb", "/_stage1/", "/_serv/")
    generated = sorted(name for name in names if any(marker in name for marker in generated_markers))
    if generated:
        fail("wheel contains local generated uarch artifacts: " + ", ".join(generated[:10]))

    import agamemnon
    from agamemnon import project
    from agamemnon.engine import bram_emit, mesh_template, status_overlay, wire_timing

    installed = Path(agamemnon.__file__).resolve()
    if installed == source_package / "__init__.py" or source_package in installed.parents:
        fail(f"smoke test imported the source tree instead of the wheel: {installed}")
    overlay_module = Path(status_overlay.__file__).resolve()
    if source_package in overlay_module.parents:
        fail("status-overlay module was imported from the checkout")
    if not mesh_template.legal_sels("RMUX", 0):
        fail("installed mesh template contains no RMUX0 selectors")
    if not bram_emit.CELLS:
        fail("installed BRAM/PLL table contains no configuration cells")
    if wire_timing.normalize_resource("OMUX1") != "OMUX01":
        fail("installed exact wire-timing loader is unavailable")

    with tempfile.TemporaryDirectory(prefix="agamemnon-wheel-smoke-") as temporary:
        temporary = Path(temporary)
        output = temporary / "counter.bin"
        env = dict(os.environ)
        help_result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "--help"],
            cwd=temporary,
            env=env,
            capture_output=True,
            text=True,
        )
        if help_result.returncode or "status-overlay" not in help_result.stdout:
            fail("installed-wheel CLI does not expose status-overlay")

        # The bounded BRAM write surface is retained-checkpoint pack-only.  It
        # must work from the installed wheel itself, not by reaching back into
        # the source checkout's qualification directory.
        bram_checkpoint = installed.parent / "sdk" / "qualified_bram_tmux9" / \
            "bram_tmux9_i0_d1_we1_routed.json"
        bram_image = temporary / "bram-tmux9-i0-d1-we1.bin"
        bram_env = {name: value for name, value in env.items()
                    if not name.startswith("AGAMEMNON_")}
        result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "pack",
             str(bram_checkpoint), str(bram_image), "--qualified-checkpoint",
             "bram-tmux9-i0-d1-we1"],
            cwd=temporary, env=bram_env, capture_output=True, text=True,
        )
        if result.returncode:
            fail("installed-wheel qualified BRAM checkpoint pack failed:\n" +
                 result.stdout + result.stderr)
        expected = {
            bram_image: "3bd2c82a2a18e2c66721de5687c940e915bc7a933f5ea88dbca45394901782df",
            Path(str(bram_image) + ".comp"):
                "221cdf15ccd9ef4d2220181861e724136a69387bb3647c4db550c1891a421ce5",
        }
        for artifact, digest in expected.items():
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if actual != digest:
                fail(f"installed-wheel qualified BRAM hash is {actual}, expected {digest}")

        # Compose from the installed module and its bundled hash-checked strict
        # routing snapshot. The input fixture may be read from the checkout;
        # imports, core template, compositor and routing tables must all come
        # from the wheel. The exact output and strict-packed image are the
        # silicon-qualified production pair.
        overlay_fixture = repository / "qualification" / \
            "mcu_ahb_status_overlay_pulse_checkpoint.json"
        composed = temporary / "status-overlay-public32.json"
        result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "status-overlay",
             str(overlay_fixture), str(composed)],
            cwd=temporary,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            fail("installed-wheel status composition failed:\n" +
                 result.stdout + result.stderr)
        actual = hashlib.sha256(composed.read_bytes()).hexdigest()
        expected = "4d93287eb085d6e48af9c15486e42398f548a447e2a4fb9e0dc3cb895c5de28f"
        if actual != expected:
            fail(f"installed-wheel composed route hash is {actual}, expected {expected}")
        overlay_image = temporary / "status-overlay-public32.bin"
        overlay_env = dict(env)
        overlay_env.update({"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"})
        result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "pack",
             str(composed), str(overlay_image)],
            cwd=temporary,
            env=overlay_env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            fail("installed-wheel status-overlay strict pack failed:\n" +
                 result.stdout + result.stderr)
        actual = hashlib.sha256(overlay_image.read_bytes()).hexdigest()
        expected = "a9a10e81aff23afa512445ffacb18eb446283eeb8f0dc2152aa4c7f704652baf"
        if actual != expected:
            fail(f"installed-wheel status-overlay image hash is {actual}, expected {expected}")

        result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "pack", str(routed), str(output)],
            cwd=temporary,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            fail("installed-wheel bitgen failed:\n" + result.stdout + result.stderr)
        if output.stat().st_size != 99944:
            fail(f"installed-wheel bitgen wrote {output.stat().st_size} bytes, expected 99944")
        if not Path(str(output) + ".comp").is_file():
            fail("installed-wheel bitgen did not write the compressed image")

        exact_profiles = {
            "mcu-fpga": "ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5",
            "serv-blinky": "fe7ecca298dc5bd929a12c3bf63c90a8323180a93016defa977de59580aa3d5a",
        }
        for template in ("mcu-blink", "fpga-io", "mcu-fpga", "serv-blinky"):
            destination = temporary / template
            result = subprocess.run(
                [
                    sys.executable, "-m", "agamemnon.cli", "new",
                    str(destination), "--board", "ag32vf303-l48",
                    "--template", template,
                ],
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                fail(
                    f"installed-wheel {template} scaffold failed:\n"
                    + result.stdout + result.stderr
                )
            manifest = destination / "agamemnon.toml"
            if not manifest.is_file():
                fail(f"installed-wheel {template} scaffold has no manifest")
            manifest_text = manifest.read_text(encoding="utf-8")
            if "@PROJECT_NAME@" in manifest_text or destination.name not in manifest_text:
                fail(f"installed-wheel {template} scaffold did not bind its project name")
            if template in exact_profiles:
                fabric = Path(project.build_qualified_fabric(
                    project.Project.load(destination)
                ))
                if fabric.stat().st_size != 99944:
                    fail(f"installed-wheel qualified {template} profile has wrong size")
                actual = hashlib.sha256(fabric.read_bytes()).hexdigest()
                if actual != exact_profiles[template]:
                    fail(
                        f"installed-wheel qualified {template} profile hash is "
                        f"{actual}, expected {exact_profiles[template]}"
                    )

        # The GPIO5 W1C derivative is selectable but deliberately not the
        # default template ABI. Exercise it from the installed wheel so its
        # profile registry and two retained payloads cannot ship separately.
        gpio5 = temporary / "mcu-fpga-gpio5-w1c"
        result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "new", str(gpio5),
             "--board", "ag32vf303-l48", "--template", "mcu-fpga"],
            cwd=temporary, env=env, capture_output=True, text=True)
        if result.returncode:
            fail("installed-wheel GPIO5 profile scaffold failed:\n" +
                 result.stdout + result.stderr)
        manifest = gpio5 / "agamemnon.toml"
        text = manifest.read_text(encoding="utf-8")
        text = text.replace(
            'qualified_profile = "l48-public32-exact-map-2026-08-15"',
            'qualified_profile = "l48-public32-gpio5-w1c-exact-map-2026-08-15"')
        manifest.write_bytes((text).encode("utf-8"))
        fabric = Path(project.build_qualified_fabric(project.Project.load(gpio5)))
        actual = hashlib.sha256(fabric.read_bytes()).hexdigest()
        expected = "bc338504e5b30fb9036d29f91c2cca6e384ef85ba2bde8ba8e79c62f05f4eb33"
        if actual != expected:
            fail(f"installed-wheel GPIO5 W1C image hash is {actual}, expected {expected}")

        # The autonomous derivative is another exact, selectable profile. It
        # ships its matching firmware example but deliberately is not default.
        autonomous = temporary / "mcu-fpga-autoevent-w1c"
        result = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "new", str(autonomous),
             "--board", "ag32vf303-l48", "--template", "mcu-fpga"],
            cwd=temporary, env=env, capture_output=True, text=True)
        if result.returncode:
            fail("installed-wheel autonomous W1C profile scaffold failed:\n" +
                 result.stdout + result.stderr)
        manifest = autonomous / "agamemnon.toml"
        text = manifest.read_text(encoding="utf-8")
        text = text.replace(
            'qualified_profile = "l48-public32-exact-map-2026-08-15"',
            'qualified_profile = "l48-public32-autoevent-w1c-exact-map-2026-08-16"')
        manifest.write_bytes((text).encode("utf-8"))
        fabric = Path(project.build_qualified_fabric(project.Project.load(autonomous)))
        actual = hashlib.sha256(fabric.read_bytes()).hexdigest()
        expected = "cb8372e669833ef103638d4f64ad86cf0e841cb448a9350dbafb79ad33ba1a9b"
        if actual != expected:
            fail(f"installed-wheel autonomous W1C image hash is {actual}, expected {expected}")

    print(f"installed wheel passed data, scaffold, and bitgen smoke tests: {wheel.name}")


if __name__ == "__main__":
    main()
