#!/usr/bin/env python3
"""Fail-closed audit for the exact L48 public16 composed map.

This checker deliberately proves more than a candidate hash.  It reproduces
the checkpoint from the hash-pinned composer, proves the qualified +4 scratch
spine was changed only at the reviewed overlay cells, proves every retained
route remains an exact prefix, audits placement/wire ownership, and regenerates
the structural route-replay source byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as composer
import generate_mcu_ahb_bank16_read_word0_structural as structural


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "mcu_ahb_public16_exact_map_routed.json"
SOURCE = HERE / "mcu_ahb_public16_exact_map_structural.v"
RAW_SHA256 = "3fd36e5b3a7f79c6da195315921658e44343513de9a85960c99e3cf638aff481"
COMP_SHA256 = "beda2dbe5ce970e2783d3c88b6df3a113f009e6e9e0d443a110f83929b7725fb"

MUTATED_BASE_CELLS = {
    "write_wait_stage",
    "read_gate0", "read_gate1", "read_gate2", "read_gate3", "read_gate6",
}
EXTENDED_BASE_NETS = {
    "hwrite", "htrans1", "write_ready_f", "hwdata[1]", "reset_request",
    "hwdata[0]", "hclk", "haddr2", "haddr3", "low_request",
}
ADDED_CELL_BELS = {
    "public_clear_event": "X14Y12_SLICE14",
    "public_counter___CARRY_SEED": "X15Y1_SLICE0",
    "public_counter___CARRY_VCC": "X15Y1_SLICE4",
    "public_counter___abc_104_auto_blifparse.cc:557:parse_blif_105_LC":
        "X15Y3_SLICE0",
    "public_counter___abc_104_auto_blifparse.cc:557:parse_blif_106_LC":
        "X15Y3_SLICE2",
    "public_counter___abc_104_auto_blifparse.cc:557:parse_blif_107_LC":
        "X19Y1_SLICE0",
    "public_counter___auto_alumacc.cc:512:replace_alu_9.fa[0].slice_CARRY":
        "X15Y1_SLICE1",
    "public_counter___auto_alumacc.cc:512:replace_alu_9.fa[1].slice_CARRY":
        "X15Y1_SLICE2",
    "public_counter___auto_alumacc.cc:512:replace_alu_9.fa[2].slice_CARRY":
        "X15Y1_SLICE3",
    "public_high_active": "X14Y12_SLICE10",
    "public_high_data0": "X15Y11_SLICE6",
    "public_high_data2": "X15Y11_SLICE10",
    "public_select_counter": "X14Y12_SLICE6",
    "public_select_status": "X14Y12_SLICE4",
    "public_set_event": "X17Y11_SLICE14",
    "public_status_hwrite_gate": "X14Y12_SLICE11",
    "public_status_pending": "X14Y9_SLICE1",
    "public_status_storage": "X14Y12_SLICE9",
}


def route_items(route):
    fields = route.split(";") if route else []
    if len(fields) % 3:
        raise SystemExit("malformed ROUTING field")
    return [tuple(fields[index:index + 3])
            for index in range(0, len(fields), 3) if fields[index]]


def _same_except_route(before, after):
    before = json.loads(json.dumps(before))
    after = json.loads(json.dumps(after))
    before.setdefault("attributes", {}).pop("ROUTING", None)
    after.setdefault("attributes", {}).pop("ROUTING", None)
    return before == after


def audit(base_bin=None, candidate_bin=None, compressed=None):
    encoded = composer.compose()
    if CANDIDATE.read_bytes() != encoded:
        raise SystemExit("tracked public16 checkpoint is not composer-reproducible")
    if composer.text_sha256(encoded) != composer.OUTPUT_SHA256:
        raise SystemExit("public16 routed hash mismatch")

    base = json.loads(composer.BASE.read_bytes())["modules"]["top"]
    candidate = json.loads(encoded)["modules"]["top"]
    if base.get("ports") != candidate.get("ports"):
        raise SystemExit("top-level ports drifted")
    if set(candidate["cells"]) - set(base["cells"]) != set(ADDED_CELL_BELS):
        raise SystemExit("added-cell inventory drifted")
    if set(base["cells"]) - set(candidate["cells"]):
        raise SystemExit("qualified base cell removed")

    for name, before in base["cells"].items():
        after = candidate["cells"][name]
        if name not in MUTATED_BASE_CELLS and after != before:
            raise SystemExit("unreviewed base-cell mutation: " + name)
        if name in MUTATED_BASE_CELLS:
            # Only LUT function and input selection may change.  Placement,
            # type, outputs, clock, FF use and every other field stay exact.
            normalized = json.loads(json.dumps(after))
            normalized["parameters"]["INIT"] = before["parameters"]["INIT"]
            normalized["connections"]["I"] = before["connections"]["I"]
            if normalized != before:
                raise SystemExit("base cell changed outside INIT/I: " + name)

    bel_owners = {}
    for name, cell in candidate["cells"].items():
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel:
            raise SystemExit("unplaced cell: " + name)
        if bel in bel_owners:
            raise SystemExit("duplicate BEL %s: %s / %s" %
                             (bel, bel_owners[bel], name))
        bel_owners[bel] = name
    for name, bel in ADDED_CELL_BELS.items():
        if candidate["cells"][name]["attributes"]["NEXTPNR_BEL"] != bel:
            raise SystemExit("added-cell BEL drift: " + name)

    if set(base["netnames"]) - set(candidate["netnames"]):
        raise SystemExit("qualified base net removed")
    changed_base_nets = set()
    for name, before in base["netnames"].items():
        after = candidate["netnames"][name]
        if after == before:
            continue
        changed_base_nets.add(name)
        if name not in EXTENDED_BASE_NETS:
            raise SystemExit("unreviewed base-net mutation: " + name)
        if not _same_except_route(before, after):
            raise SystemExit("base net changed outside ROUTING: " + name)
        old_route = route_items(before.get("attributes", {}).get("ROUTING", ""))
        new_route = route_items(after.get("attributes", {}).get("ROUTING", ""))
        if new_route[:len(old_route)] != old_route or len(new_route) <= len(old_route):
            raise SystemExit("base route was not preserved as an exact prefix: " + name)
    if changed_base_nets != EXTENDED_BASE_NETS:
        raise SystemExit("extended-base-net inventory drifted")

    wire_owners = {}
    routed_nets = 0
    for name, net in candidate["netnames"].items():
        route = route_items(net.get("attributes", {}).get("ROUTING", ""))
        if not route:
            continue
        routed_nets += 1
        for dst, pip, strength in route:
            if strength not in {"1", "5"}:
                raise SystemExit("unexpected route strength on " + name)
            for wire in (dst, pip.split(".", 1)[0] if pip else None):
                if not wire:
                    continue
                owner = wire_owners.get(wire)
                if owner is not None and owner != name:
                    raise SystemExit("cross-net wire owner %s: %s / %s" %
                                     (wire, owner, name))
                wire_owners[wire] = name

    if len(candidate["cells"]) != 119 or routed_nets != 103:
        raise SystemExit("expected 119 placed cells and 103 routed nets")

    source_text, emitted = structural.generate(CANDIDATE)
    if emitted != 118 or source_text.encode("ascii") != SOURCE.read_bytes():
        raise SystemExit("public16 structural source is not generator-reproducible")

    if (base_bin is None) != (candidate_bin is None):
        raise SystemExit("provide both --base-bin and --candidate-bin")
    if base_bin is not None:
        before = Path(base_bin).read_bytes()
        after = Path(candidate_bin).read_bytes()
        if len(before) != 99_944 or len(after) != 99_944:
            raise SystemExit("packed images must be exactly 99,944 bytes")
        if hashlib.sha256(after).hexdigest() != RAW_SHA256:
            raise SystemExit("public16 raw bitstream hash mismatch")
        if before == after:
            raise SystemExit("public16 bitstream unexpectedly equals its +4 base")
    if compressed is not None:
        packed = Path(compressed).read_bytes()
        if hashlib.sha256(packed).hexdigest() != COMP_SHA256:
            raise SystemExit("public16 compressed bitstream hash mismatch")

    print("PASS: composer-reproducible public16 checkpoint")
    print("PASS: 101-cell +4 base retained; 6 reviewed overlay cells and "
          "10 append-only route extensions")
    print("PASS: 18 exact added cells; 119 unique BELs, 103 routed nets, "
          "single-owner wires")
    print("PASS: structural source regenerated exactly (118 cells + packer GND)")
    if base_bin is not None:
        print("PASS: exact public16 raw bitstream hash pinned")
    if compressed is not None:
        print("PASS: exact public16 compressed bitstream hash pinned")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-bin", type=Path)
    parser.add_argument("--candidate-bin", type=Path)
    parser.add_argument("--compressed", type=Path)
    args = parser.parse_args()
    audit(args.base_bin, args.candidate_bin, args.compressed)


if __name__ == "__main__":
    main()
