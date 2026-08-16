#!/usr/bin/env python3
"""Fail-closed static audit for the bounded L48 PIN_25 bidirectional campaign.

The four images must already have been built into ``tools/lab``.  This checker
does not touch hardware.  It proves the electrical safety envelope visible in
the routed netlists, checks the exact characterized PIN_25 input/OE corridors,
requires zero selector debt from a fresh repack, and requires that repack to be
byte-identical to the proposed board image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "agamemnon" / "engine"

ARMS = ("release", "drive", "dynamic", "readback")
INPUT_PIPS = (
    "X0Y4_InputMUX00.X1Y4_RMUX11",
    "X1Y4_RMUX11.X1Y4_IMUX09",
)
OE_PIPS = (
    "X10Y4_OMUX02.X10Y4_RMUX08",
    "X10Y4_RMUX08.X11Y4_RMUX26",
    "X11Y4_RMUX26.X8Y4_RMUX13",
    "X8Y4_RMUX13.X4Y4_RMUX49",
    "X4Y4_RMUX49.X0Y4_RMUX00",
    "X0Y4_RMUX00.X0Y4_IOMUX06",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module(path: Path) -> dict:
    design = json.loads(path.read_text(encoding="utf-8"))
    assert list(design["modules"]) == ["top"], path
    return design["modules"]["top"]


def _cell_at(module: dict, bel: str) -> tuple[str, dict]:
    found = [(name, cell) for name, cell in module["cells"].items()
             if cell.get("attributes", {}).get("NEXTPNR_BEL") == bel]
    assert len(found) == 1, (bel, [name for name, _ in found])
    return found[0]


def _route_pips(module: dict, net: str) -> tuple[str, ...]:
    route = module["netnames"][net].get("attributes", {}).get("ROUTING", "")
    fields = route.split(";")
    return tuple(fields[index] for index in range(1, len(fields), 3) if fields[index])


def _assert_exact_pips(module: dict, net: str, expected: tuple[str, ...]) -> None:
    # nextpnr serializes locked branches from sink back toward source; require
    # exact membership and cardinality rather than depending on that order.
    actual = _route_pips(module, net)
    assert len(actual) == len(expected) and set(actual) == set(expected), (net, actual)


def _assert_ports(cell: dict, expected: set[str]) -> None:
    assert set(cell["connections"]) == expected, (cell["connections"], expected)


def _assert_local_low(cell: dict) -> None:
    assert cell["attributes"].get("AGRV2K_IO_DATA_GND", "").endswith("1")
    assert cell["connections"]["I"] == []


def _repack_clean(routed: Path, image: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="agamemnon-pin25-audit-") as directory:
        out = Path(directory) / image.name
        env = dict(os.environ, AGAMEMNON_DATA=str(ROOT / "agamemnon" / "chipdb"))
        result = subprocess.run(
            [sys.executable, str(ENGINE / "to_bin.py"), str(routed), str(out)],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        transcript = result.stdout + result.stderr
        assert result.returncode == 0, transcript
        match = re.search(
            r"data pips: (\d+) total, (\d+) mapped .*"
            r"0 legacy-abs, 0 predicted\), 0 unmapped",
            transcript,
        )
        assert match, transcript
        assert match.group(1) == match.group(2), transcript
        assert out.read_bytes() == image.read_bytes(), image
    return match.group(1)


def audit(directory: Path) -> list[dict]:
    source = (ROOT / "qualification" / "bidir_pin25_campaign.v").read_text(
        encoding="utf-8")
    assert "assign link = drive_low ? 1'b0 : 1'bz;" in source
    assert "1'b1" not in source  # no campaign image can actively drive high

    modules = {}
    rows = []
    for arm in ARMS:
        routed = directory / f"bidir_pin25_{arm}_routed.json"
        image = directory / f"bidir_pin25_{arm}.bin"
        assert routed.is_file() and image.is_file(), (routed, image)
        modules[arm] = _module(routed)
        rows.append({
            "arm": arm,
            "image_sha256": _sha256(image),
            "routed_sha256": _sha256(routed),
            "mapped_pips": int(_repack_clean(routed, image)),
        })

    # A: electrically incapable of driving PIN_25; exact ingress to an
    # identity boundary and a qualified PIN_18 observation output.
    release = modules["release"]
    _, link = _cell_at(release, "X0Y4_IOB0")
    _assert_ports(link, {"PAD", "O"})
    _assert_exact_pips(release, "$iopadmap$link", INPUT_PIPS)
    _cell_at(release, "X1Y4_SLICE2")
    _, observed = _cell_at(release, "X18Y13_OPAD0")
    _assert_ports(observed, {"PAD", "I"})
    assert "X18Y13_RMUX28.X18Y13_IOMUX00" in _route_pips(
        release, "$iopadmap$observed")

    # B: no ingress or OE path and an exact local zero at the pad data input.
    drive = modules["drive"]
    _, link = _cell_at(drive, "X0Y4_IOB0")
    _assert_ports(link, {"PAD", "I"})
    _assert_local_low(link)

    # C/D: exact active-high OE presentation and exact input corridor.  The
    # PIN_10 control is input-only; the pad data path remains a local zero.
    for arm in ("dynamic", "readback"):
        module = modules[arm]
        _, link = _cell_at(module, "X0Y4_IOB0")
        _assert_ports(link, {"PAD", "I", "O", "EN"})
        _assert_local_low(link)
        _, control = _cell_at(module, "X20Y13_IPAD1")
        _assert_ports(control, {"PAD", "O"})
        _, oe = _cell_at(module, "X10Y4_SLICE0")
        assert oe["parameters"]["INIT"] == "1010101010101010"
        assert link["connections"]["EN"] == oe["connections"]["F"]
        _assert_exact_pips(module, "$quad_oe0_identity_NET", OE_PIPS)
        _assert_exact_pips(module, "$iopadmap$link", INPUT_PIPS)
        _cell_at(module, "X1Y4_SLICE2")

    # C has no external observation driver; D adds exactly the qualified one.
    assert not any(cell.get("attributes", {}).get("NEXTPNR_BEL") == "X18Y13_OPAD0"
                   for cell in modules["dynamic"]["cells"].values())
    _, observed = _cell_at(modules["readback"], "X18Y13_OPAD0")
    _assert_ports(observed, {"PAD", "I"})
    assert "X18Y13_RMUX28.X18Y13_IOMUX00" in _route_pips(
        modules["readback"], "$iopadmap$observed")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path,
                        default=ROOT / "tools" / "lab")
    args = parser.parse_args()
    rows = audit(args.directory.resolve())
    print(json.dumps({"result": "pass", "arms": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
