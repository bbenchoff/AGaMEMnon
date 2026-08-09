#!/usr/bin/env python3
"""Smoke-test an installed AGaMEMnon wheel from outside the source tree."""

import os
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def fail(message):
    raise SystemExit(message)


def main():
    if len(sys.argv) != 3:
        fail("usage: installed_wheel_smoke.py WHEEL ROUTED_FIXTURE")

    wheel = Path(sys.argv[1]).resolve()
    routed = Path(sys.argv[2]).resolve()
    repository = Path(__file__).resolve().parents[1]
    source_package = repository / "agamemnon"

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    required = {
        "agamemnon/engine/features/__init__.py",
        "agamemnon/engine/features/protocol.py",
        "agamemnon/engine/features/routing.py",
        "agamemnon/archdec_cfg/alta_tile_agr_cfg.csv",
        "agamemnon/chipdb/corpus_conduction.csv",
        "agamemnon/chipdb/bondmap_L100.csv",
        "agamemnon/chipdb/bondmap_L64.csv",
        "agamemnon/chipdb/bondmap_L48.csv",
        "agamemnon/chipdb/bondmap_Q32.csv",
        "agamemnon/chipdb/bondmaps.json",
        "agamemnon/chipdb/route_through_footprints.csv",
        "agamemnon/chipdb/wire_timing_exact_safe.json",
        "agamemnon/chipdb/wire_timing_exact_safe_manifest.json",
        "agamemnon/chipdb/sel_edge_pairs.agdb",
        "agamemnon/chipdb/train_lut.agdb",
        "agamemnon/chipdb/sel_tables.agdb",
        "agamemnon/engine/mesh_resolver_table.json",
        "agamemnon/engine/pips_bram_pll.csv",
        "agamemnon/engine/uarch/agrv2k/README.md",
        "agamemnon/engine/uarch/agrv2k/agrv2k.cc",
        "agamemnon/engine/uarch/agrv2k/build.sh",
        "agamemnon/sim/ahb_slave_model.v",
        "agamemnon/sdk/qualified_fabric_profiles.json",
        "agamemnon/templates/mcu-blink/agamemnon.toml",
        "agamemnon/templates/mcu-blink/src/main.c",
        "agamemnon/templates/mcu-fpga-registers/agamemnon.toml",
        "agamemnon/templates/mcu-fpga-registers/logic/top.v",
        "agamemnon/templates/mcu-fpga-registers/logic/id_scratch8_L48_routed.json",
        "agamemnon/templates/mcu-fpga-registers/src/main.c",
        "agamemnon/templates/serv-blinky/agamemnon.toml",
        "agamemnon/templates/serv-blinky/board.pcf",
        "agamemnon/templates/serv-blinky/logic/top.v",
        "agamemnon/templates/serv-blinky/logic/serv_rtl.v",
        "agamemnon/templates/serv-blinky/logic/serv_blinky_L48_routed.json",
        "agamemnon/templates/serv-blinky/src/load_fabric.c",
    }
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
    from agamemnon.engine import bram_emit, mesh_template, wire_timing

    installed = Path(agamemnon.__file__).resolve()
    if installed == source_package / "__init__.py" or source_package in installed.parents:
        fail(f"smoke test imported the source tree instead of the wheel: {installed}")
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
            "mcu-fpga": "4cd1551d1202c9768554b75deddcace93291e8444b6d6c82f9762936a7dc737b",
            "serv-blinky": "fe7ecca298dc5bd929a12c3bf63c90a8323180a93016defa977de59580aa3d5a",
        }
        for template in ("mcu-blink", "mcu-fpga", "serv-blinky"):
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

    print(f"installed wheel passed data, scaffold, and bitgen smoke tests: {wheel.name}")


if __name__ == "__main__":
    main()
