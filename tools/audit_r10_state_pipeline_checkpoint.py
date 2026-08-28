"""Fail-closed audit for the R10 R8-preserved two-stage observer pair."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from compose_r10_state_pipeline_checkpoint import (
    CompositionError,
    _cell_map,
    _module,
    _net_map,
    compose,
)


EXPECTED_ROUTE_DELTA = {
    "first_master_state[0]": {
        "removed": set(),
        "added": {"X14Y11_OMUX13.X14Y11_IMUX24"},
    },
    "first_master_state[1]": {
        "removed": set(),
        "added": {
            "X14Y11_OMUX15.X15Y11_RMUX33",
            "X15Y11_RMUX33.X14Y11_RMUX34",
            "X14Y11_RMUX34.X14Y11_IMUX28",
        },
    },
    "dut.start_pulse": {
        "removed": {"X14Y11_RMUX94.X14Y11_IMUX24"},
        "added": set(),
    },
    "dut.command_pending": {
        "removed": {
            "X16Y10_RMUX85.X16Y11_RMUX49",
            "X16Y11_RMUX49.X14Y11_RMUX22",
            "X14Y11_RMUX22.X14Y11_IMUX28",
        },
        "added": set(),
    },
}

EXPECTED_IMAGE_DIFF_OFFSETS = {
    2747, 2863, 2979, 3095, 99940, 99941, 99942, 99943,
}


def _route_pips(route: str) -> set[str]:
    if not route.strip():
        return set()
    parts = route.split(";")
    if len(parts) % 3:
        raise CompositionError("malformed routed triple sequence")
    return {parts[index + 1] for index in range(0, len(parts), 3)
            if parts[index + 1]}


def _recursive_diffs(left, right, path=""):
    if type(left) is not type(right):
        return [(path, left, right)]
    if isinstance(left, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{key}"
            if key not in left or key not in right:
                result.append((child, left.get(key), right.get(key)))
            else:
                result.extend(_recursive_diffs(left[key], right[key], child))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [(path + "/length", len(left), len(right))]
        result = []
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(_recursive_diffs(a, b, f"{path}/{index}"))
        return result
    return [] if left == right else [(path, left, right)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(r8_path: Path, r10_source_path: Path, active_route_path: Path,
          control_route_path: Path, active_image_path: Path,
          control_image_path: Path) -> dict:
    r8_document = json.loads(r8_path.read_text(encoding="utf-8"))
    r10_source_document = json.loads(
        r10_source_path.read_text(encoding="utf-8")
    )
    active_document = json.loads(active_route_path.read_text(encoding="utf-8"))
    control_document = json.loads(control_route_path.read_text(encoding="utf-8"))

    # Re-running the composer on independent objects proves the source pair has
    # exactly the four admitted endpoint-signature changes before physical data
    # from R8 is allowed to enter it.
    _, composition = compose(r8_document, r10_source_document)
    r8 = _module(r8_document)
    r10_source = _module(r10_source_document)
    active = _module(active_document)
    mapping = _cell_map(r8, r10_source)

    if len(active["cells"]) != 145:
        raise CompositionError("final route does not contain exact 145 cells")
    for r10_name, r8_name in mapping.items():
        candidate = active["cells"][r10_name]
        reference = r8["cells"][r8_name]
        if (candidate.get("type"), candidate.get("parameters", {})) != (
                reference.get("type"), reference.get("parameters", {})):
            raise CompositionError(f"final cell signature drift: {r10_name}")
        if candidate.get("attributes", {}).get("NEXTPNR_BEL") != \
                reference.get("attributes", {}).get("NEXTPNR_BEL"):
            raise CompositionError(f"final BEL drift: {r10_name}")

    changed_nets = {}
    for r10_name, r10_net in r10_source["netnames"].items():
        r8_name = _net_map(r10_name, r8)
        reference_pips = _route_pips(
            r8["netnames"][r8_name]["attributes"]["ROUTING"]
        )
        try:
            final_route = active["netnames"][r10_name]["attributes"]["ROUTING"]
        except KeyError as exc:
            raise CompositionError(f"final route missing net {r10_name}") from exc
        final_pips = _route_pips(final_route)
        if final_pips != reference_pips:
            changed_nets[r10_name] = {
                "removed": reference_pips - final_pips,
                "added": final_pips - reference_pips,
            }
    if changed_nets != EXPECTED_ROUTE_DELTA:
        raise CompositionError(f"unexpected final route delta: {changed_nets}")

    route_diffs = _recursive_diffs(active_document, control_document)
    expected_path = "/modules/top/cells/dut.request_arm_source_LC/parameters/INIT"
    if route_diffs != [(expected_path, "1111111111111111", "0000000000000000")]:
        raise CompositionError(f"active/control route drift: {route_diffs}")

    active_image = active_image_path.read_bytes()
    control_image = control_image_path.read_bytes()
    if len(active_image) != 99944 or len(control_image) != 99944:
        raise CompositionError("active/control image length is not exact 99944")
    image_diffs = {
        index for index, (left, right) in enumerate(zip(active_image, control_image))
        if left != right
    }
    if image_diffs != EXPECTED_IMAGE_DIFF_OFFSETS:
        raise CompositionError(
            f"active/control image offsets drift: {sorted(image_diffs)}"
        )

    return {
        "verdict": "accept-r8-preserved-r10-desk-candidate",
        "cells_exact": len(mapping),
        "source_nets_exact": composition["nets"],
        "endpoint_signature_drift": composition["endpoint_drift"],
        "route_delta": {
            name: {key: sorted(value) for key, value in delta.items()}
            for name, delta in changed_nets.items()
        },
        "active_route_sha256": _sha256(active_route_path),
        "control_route_sha256": _sha256(control_route_path),
        "active_image_sha256": _sha256(active_image_path),
        "control_image_sha256": _sha256(control_image_path),
        "image_diff_offsets": sorted(image_diffs),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("r8")
    parser.add_argument("r10_source")
    parser.add_argument("active_route")
    parser.add_argument("control_route")
    parser.add_argument("active_image")
    parser.add_argument("control_image")
    args = parser.parse_args()
    result = audit(*map(Path, (
        args.r8, args.r10_source, args.active_route, args.control_route,
        args.active_image, args.control_image,
    )))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
