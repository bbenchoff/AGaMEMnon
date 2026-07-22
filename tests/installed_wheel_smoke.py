#!/usr/bin/env python3
"""Smoke-test an installed AGaMEMnon wheel from outside the source tree."""

import os
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
        "agamemnon/archdec_cfg/alta_tile_agr_cfg.csv",
        "agamemnon/chipdb/corpus_conduction.csv",
        "agamemnon/chipdb/bondmap_L100.csv",
        "agamemnon/chipdb/bondmap_L64.csv",
        "agamemnon/chipdb/bondmap_L48.csv",
        "agamemnon/chipdb/bondmap_Q32.csv",
        "agamemnon/chipdb/bondmaps.json",
        "agamemnon/chipdb/sel_edge_pairs.agdb",
        "agamemnon/chipdb/train_lut.agdb",
        "agamemnon/chipdb/sel_tables.agdb",
        "agamemnon/engine/mesh_resolver_table.json",
        "agamemnon/engine/pips_bram_pll.csv",
        "agamemnon/engine/uarch/agrv2k/README.md",
        "agamemnon/engine/uarch/agrv2k/agrv2k.cc",
        "agamemnon/engine/uarch/agrv2k/build.sh",
        "agamemnon/sim/ahb_slave_model.v",
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
    from agamemnon.engine import bram_emit, mesh_template

    installed = Path(agamemnon.__file__).resolve()
    if installed == source_package / "__init__.py" or source_package in installed.parents:
        fail(f"smoke test imported the source tree instead of the wheel: {installed}")
    if not mesh_template.legal_sels("RMUX", 0):
        fail("installed mesh template contains no RMUX0 selectors")
    if not bram_emit.CELLS:
        fail("installed BRAM/PLL table contains no configuration cells")

    with tempfile.TemporaryDirectory(prefix="agamemnon-wheel-smoke-") as temporary:
        output = Path(temporary) / "counter.bin"
        env = dict(os.environ)
        env["AGAMEMNON_MESH_TEMPLATE"] = "1"
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

    print(f"installed wheel passed data and bitgen smoke tests: {wheel.name}")


if __name__ == "__main__":
    main()
