#!/usr/bin/env python3
"""Audit the exact +4 scratch candidate and its optional packed images."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agamemnon.engine import physmap

import compose_mcu_ahb_bank16_public_scratch4 as composer


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "mcu_ahb_register_bank16_public_scratch4_routed.json"
RAW_SHA256 = "2aa4d1d65c57c1ae28612f5743b08a7683179786e2d467c20166add1fba60882"
COMP_SHA256 = "dd20ea9549bf0d5f0c4dc09988a2696aeab57cb4f299ac12c136e4842e04e516"


def recursive_diffs(left, right, path=""):
    if type(left) is not type(right):
        return [(path, left, right)]
    if isinstance(left, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                result.append((path + "/" + key, left.get(key), right.get(key)))
            else:
                result.extend(recursive_diffs(left[key], right[key],
                                              path + "/" + key))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [(path, left, right)]
        result = []
        for index, (lvalue, rvalue) in enumerate(zip(left, right)):
            result.extend(recursive_diffs(lvalue, rvalue,
                                          path + "/%d" % index))
        return result
    return [] if left == right else [(path, left, right)]


def expected_bin_xor():
    result = {}
    changes = [((14, 12, 0), 0x0044, 0x0088),
               ((14, 12, 5), 0x1111, 0x2222)]
    for (x, y, z), old, new in changes:
        for bit in range(16):
            if ((old ^ new) >> bit) & 1:
                byte, mask = physmap.init_bit_pos(x, y, z, bit)
                result[8 + byte] = result.get(8 + byte, 0) | mask
    return result


def audit(base_bin=None, candidate_bin=None, compressed=None):
    encoded = composer.compose()
    if CANDIDATE.read_bytes() != encoded:
        raise SystemExit("tracked +4 candidate is not composer-reproducible")
    base = json.loads(composer.BASE.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    expected_paths = {
        "/modules/top/cells/hwrite_word0_gate/parameters/INIT",
        "/modules/top/cells/read_word0/parameters/INIT",
    }
    diffs = recursive_diffs(base, candidate)
    if {item[0] for item in diffs} != expected_paths or len(diffs) != 2:
        raise SystemExit("candidate differs outside the two admitted INITs")
    btop = base["modules"]["top"]
    ctop = candidate["modules"]["top"]
    for name, cell in btop["cells"].items():
        if cell["attributes"]["NEXTPNR_BEL"] != \
                ctop["cells"][name]["attributes"]["NEXTPNR_BEL"]:
            raise SystemExit("BEL drift: %s" % name)
    for name, net in btop["netnames"].items():
        if net.get("attributes", {}).get("ROUTING") != \
                ctop["netnames"][name].get("attributes", {}).get("ROUTING"):
            raise SystemExit("route drift: %s" % name)

    if (base_bin is None) != (candidate_bin is None):
        raise SystemExit("provide both --base-bin and --candidate-bin")
    if base_bin is not None:
        before = Path(base_bin).read_bytes()
        after = Path(candidate_bin).read_bytes()
        actual = {index: left ^ right for index, (left, right) in
                  enumerate(zip(before, after)) if left != right}
        expected = expected_bin_xor()
        crc = set(range(99940, 99944))
        if {index: mask for index, mask in actual.items()
                if index not in crc} != expected:
            raise SystemExit("packed config delta is not the two admitted LUTs")
        if set(actual) != set(expected) | crc:
            raise SystemExit("packed image changed outside LUT bits and CRC")
        if hashlib.sha256(after).hexdigest() != RAW_SHA256:
            raise SystemExit("candidate bitstream hash mismatch")
    if compressed is not None and \
            hashlib.sha256(Path(compressed).read_bytes()).hexdigest() != COMP_SHA256:
        raise SystemExit("compressed bitstream hash mismatch")
    print("PASS: exactly two INIT changes; 101 BELs and 83 routes unchanged")
    if base_bin is not None:
        print("PASS: exact LUT config XOR + CRC only; raw hash pinned")
    if compressed is not None:
        print("PASS: compressed hash pinned")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-bin", type=Path)
    parser.add_argument("--candidate-bin", type=Path)
    parser.add_argument("--compressed", type=Path)
    args = parser.parse_args()
    audit(args.base_bin, args.candidate_bin, args.compressed)


if __name__ == "__main__":
    main()
