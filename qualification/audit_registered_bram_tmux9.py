#!/usr/bin/env python3
"""Audit the exact pack-only registered-source TMUX09 BRAM surface.

The audit repacks all four packaged checkpoints, verifies every pinned hash and
signature, inventories the two low/high semantic diffs, and proves residual
changed bits are only LUT INIT cells for the intentionally relocated
DataInA[1] source and nextpnr's relocated constant packer cells.  It is not a
route generator and does not promote TMUX09 into the ordinary graph.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agamemnon import cli
from agamemnon.engine import agasc, bitstream_inspect, physmap
from agamemnon.engine.features.bram import _tmux9_profile_signature


OUTPUT = ROOT / "qualification" / "registered_bram_tmux9_pack_audit.json"
PROFILES = tuple(
    name for name, row in cli.QUALIFIED_ROUTE_PROFILES.items()
    if row.get("pack_only")
)
PAIRS = (
    ("bram-tmux9-i0-d1-we0", "bram-tmux9-i0-d1-we1"),
    ("bram-tmux9-i1-d0-we0", "bram-tmux9-i1-d0-we1"),
)
WRITE_EDGES = (
    "X15Y4_RMUX86.X13Y4_TMUX09",
    "X13Y4_TMUX09.X13Y4_KMUX03",
)
DATA_ROUTE = (
    "X14Y4_OMUX41;;1;X13Y4_IMUX29;"
    "X13Y4_RMUX05.X13Y4_IMUX29;5;X13Y4_RMUX05;"
    "X15Y4_RMUX03.X13Y4_RMUX05;5;X15Y4_RMUX03;"
    "X14Y4_RMUX74.X15Y4_RMUX03;5;X14Y4_RMUX74;"
    "X14Y4_OMUX41.X14Y4_RMUX74;5"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bit_count(value: int) -> int:
    try:
        return value.bit_count()
    except AttributeError:
        return bin(value).count("1")


def clean_env():
    return {key: value for key, value in os.environ.items()
            if not key.startswith("AGAMEMNON_")}


def canonical_module_hash(module) -> str:
    data = json.dumps(module, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def kmux_field(raw: bytes):
    wanted = {29, 30, 33, 34, 35, 40, 43}
    with (Path(cli.CHIPDB) / "bram_cell.csv").open(
            newline="", encoding="utf-8") as stream:
        cells = {
            int(row["sel"]): (int(row["byte"]), int(row["mask"]))
            for row in csv.DictReader(stream)
            if row["mux"] == "CFG_KMUX" and
            (int(row["x"]), int(row["y"])) == (13, 4) and
            int(row["sel"]) in wanted
        }
    return {str(sel): bool(raw[byte] & mask)
            for sel, (byte, mask) in sorted(cells.items())}


def allowed_lut_masks(modules):
    allowed = {}
    owners = {}
    names = {"src_d1", "$PACKER_GND", "$PACKER_VCC"}
    for label, module in modules.items():
        for name, cell in module["cells"].items():
            if name not in names:
                continue
            bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
            match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", bel)
            if match is None:
                raise SystemExit(f"{label}: {name} has invalid BEL {bel}")
            x, y, z = map(int, match.groups())
            for bit in range(16):
                byte, mask = physmap.init_bit_pos(x, y, z, bit)
                allowed[byte] = allowed.get(byte, 0) | mask
                owners.setdefault(byte, set()).add(f"{label}:{name}@{bel}")
    return allowed, owners


def generate():
    profiles = {}
    images = {}
    modules = {}
    with tempfile.TemporaryDirectory(prefix="agamemnon-tmux9-audit-") as temporary:
        temporary = Path(temporary)
        for profile in PROFILES:
            registry = cli.QUALIFIED_ROUTE_PROFILES[profile]
            root = Path(cli._qualified_profile_root(registry))
            source = root / registry["source"]
            checkpoint = root / registry["checkpoint"]
            document = json.loads(checkpoint.read_text(encoding="utf-8"))
            module = document["modules"]["top"]
            modules[profile] = module
            if not _tmux9_profile_signature(module, profile):
                raise SystemExit(f"{profile}: exact semantic signature rejected")
            output = temporary / (profile + ".bin")
            result = subprocess.run(
                [sys.executable, "-m", "agamemnon.cli", "pack", str(checkpoint),
                 str(output), "--qualified-checkpoint", profile],
                cwd=ROOT, env=clean_env(), capture_output=True, text=True,
            )
            if result.returncode:
                raise SystemExit(result.stdout + result.stderr)
            if sha(output) != registry["bitstream_sha256"] or \
                    sha(Path(str(output) + ".comp")) != registry["compressed_sha256"]:
                raise SystemExit(f"{profile}: pack hash mismatch")
            header, raw, _compressed = cli._read_fabric_image(output)
            images[profile] = (header, raw)
            h1_route = module["netnames"]["h1"]["attributes"]["ROUTING"]
            high = profile.endswith("we1")
            data_cell = module["cells"]["src_d1"]
            data_route = module["netnames"]["din1"]["attributes"]["ROUTING"].strip()
            expected_bel = "X14Y4_SLICE13" if high else "X14Y4_SLICE0"
            expected_route = DATA_ROUTE if high else ""
            if data_cell["attributes"]["NEXTPNR_BEL"] != expected_bel or \
                    data_route != expected_route:
                raise SystemExit(f"{profile}: DataInA[1] presentation drift")
            if high != all(edge in h1_route for edge in WRITE_EDGES):
                raise SystemExit(f"{profile}: write-arm route drift")
            profiles[profile] = {
                "source": source.relative_to(ROOT).as_posix(),
                "source_sha256": sha(source),
                "checkpoint": checkpoint.relative_to(ROOT).as_posix(),
                "checkpoint_sha256": sha(checkpoint),
                "module_sha256": canonical_module_hash(module),
                "bitstream_sha256": sha(output),
                "compressed_sha256": sha(Path(str(output) + ".comp")),
                "signature": "exact",
                "wea_route": "TMUX09->KMUX03" if high else "absent",
                "data_source_bel": expected_bel,
                "data_source_route": expected_route or "absent",
                "kmux03_field": kmux_field(raw),
            }

        pairs = []
        for low, high in PAIRS:
            low_header, low_raw = images[low]
            high_header, high_raw = images[high]
            diff = bitstream_inspect.compare(
                low_header, low_raw, high_header, high_raw, cli.CHIPDB,
            )
            allowed, owners = allowed_lut_masks({low: modules[low], high: modules[high]})
            actual_bits = sum(bit_count(a ^ b) for a, b in
                              zip(low_raw[:agasc.CRC_OFFSET], high_raw[:agasc.CRC_OFFSET]))
            named_bits = len(diff["added"]) + len(diff["removed"])
            residual_bits = 0
            residual = []
            for change in diff["raw"]:
                mask = change["before"] ^ change["after"]
                residual_bits += bit_count(mask)
                if mask & ~allowed.get(change["offset"], 0):
                    raise SystemExit(
                        f"{low}->{high}: residual change outside DataInA[1] LUTs")
                residual.append({
                    **change,
                    "changed_mask": mask,
                    "lut_owners": sorted(owners.get(change["offset"], ())),
                })
            if actual_bits != named_bits + residual_bits:
                raise SystemExit(f"{low}->{high}: unattributed changed bit")
            pairs.append({
                "low": low,
                "high": high,
                "changed_bits": actual_bits,
                "named_feature_bits": named_bits,
                "relocated_lut_bits": residual_bits,
                "unattributed_bits": 0,
                "added": diff["added"],
                "removed": diff["removed"],
                "lut_residual": residual,
            })

    return {
        "schema": 1,
        "scope": "four hash-bound retained X13Y4 x18 TMUX09 pack-only profiles",
        "ordinary_build_claim": False,
        "ordinary_routing_claim": False,
        "profiles": profiles,
        "paired_semantic_diffs": pairs,
        "result": "all exact hashes and signatures reproduced; every paired changed bit attributed",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="replace the checked-in deterministic audit report")
    parser.add_argument("--check", action="store_true",
                        help="fail if the checked-in report differs")
    args = parser.parse_args()
    report = generate()
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != encoded:
            raise SystemExit("registered TMUX09 audit report is stale")
    elif args.write:
        OUTPUT.write_bytes(encoded.encode("utf-8"))
    else:
        sys.stdout.write(encoded)
    print("registered TMUX09 audit passed", file=sys.stderr)


if __name__ == "__main__":
    main()
