#!/usr/bin/env python3
"""Fail-closed desk audit for the frozen N58 HWDATA25 HIL package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agamemnon.engine.lzw_codec import decode, encode  # noqa: E402
from qualification.n58_hwdata25_hil_s01.classifier import (  # noqa: E402
    COMPLETE_HIGH_RUNS_MIN,
    COMPLETE_LOW_RUNS_MIN,
    EXPECTED_SAMPLES,
    HIGH_FRACTION_MAX,
    HIGH_FRACTION_MIN,
    RUN_LENGTH_MAX,
    RUN_LENGTH_MIN,
    TRANSITIONS_MIN,
)


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot load canonical JSON {path.name}: {exc}") from exc
    require(isinstance(value, dict), f"{path.name}: top level must be an object")
    return value


def git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode:
        raise AuditError(
            f"git {' '.join(arguments)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def audit_file_table(table: dict[str, Any], directory: Path, label: str) -> None:
    require(isinstance(table, dict) and table, f"{label}: nonempty object required")
    if label == "artifacts":
        actual = sorted(path.name for path in directory.iterdir() if path.is_file())
        require(actual == sorted(table), f"{label}: undeclared or missing files: {actual}")
    for name, identity in table.items():
        require(
            isinstance(name, str)
            and name == Path(name).name
            and not Path(name).is_absolute(),
            f"{label}: unsafe path {name!r}",
        )
        require(
            isinstance(identity, dict) and set(identity) == {"sha256", "size"},
            f"{label}/{name}: exact sha256/size identity required",
        )
        path = directory / name
        require(path.is_file(), f"{label}/{name}: missing")
        require(path.stat().st_size == identity["size"], f"{label}/{name}: size drift")
        require(sha256(path) == identity["sha256"], f"{label}/{name}: SHA-256 drift")


def routing(net: dict[str, Any], label: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    text = net.get("attributes", {}).get("ROUTING")
    require(isinstance(text, str) and text, f"{label}: ROUTING string required")
    fields = text.split(";")
    require(len(fields) % 3 == 0, f"{label}: malformed ROUTING triples")
    roots: list[str] = []
    edges: list[tuple[str, str]] = []
    for offset in range(0, len(fields), 3):
        wire, pip, direction = fields[offset : offset + 3]
        require(wire and direction == "1", f"{label}: malformed routing record")
        if not pip:
            roots.append(wire)
            continue
        parts = pip.split(".")
        require(len(parts) == 2 and all(parts), f"{label}: malformed PIP {pip!r}")
        source, destination = parts
        require(destination == wire, f"{label}: PIP destination/wire mismatch")
        edges.append((source, destination))
    require(len(roots) == 1, f"{label}: exactly one route root required")
    return roots[0], edges, roots


def walk_route(root: str, edges: list[tuple[str, str]], label: str) -> list[str]:
    remaining = list(edges)
    path = [root]
    while remaining:
        matches = [edge for edge in remaining if edge[0] == path[-1]]
        require(len(matches) == 1, f"{label}: route is branched or disconnected at {path[-1]}")
        edge = matches[0]
        path.append(edge[1])
        remaining.remove(edge)
    require(len(path) == len(set(path)), f"{label}: route contains a cycle")
    return path


def module(path: Path) -> dict[str, Any]:
    document = load_json(path)
    require(set(document.get("modules", {})) == {"top"}, f"{path.name}: exact top module required")
    serialized = json.dumps(document, sort_keys=True)
    forbidden = [r"[A-Za-z]:\\\\", r"/mnt/[A-Za-z]/", r"/home/", r"/Users/"]
    require(
        not any(re.search(pattern, serialized) for pattern in forbidden),
        f"{path.name}: workstation identity leaked into routed JSON",
    )
    return document["modules"]["top"]


def audit_routes(manifest: dict[str, Any]) -> None:
    route_contract = manifest["route_contract"]
    candidate = module(PACKAGE_DIR / "artifacts" / "candidate_routed.json")
    control = module(PACKAGE_DIR / "artifacts" / "control_routed.json")
    candidate_cells = candidate.get("cells", {})
    control_cells = control.get("cells", {})

    endpoint_cells = [
        (name, cell) for name, cell in candidate_cells.items() if cell.get("type") == "MCU_DIN"
    ]
    require(len(endpoint_cells) == 1, "candidate: exactly one MCU_DIN endpoint required")
    endpoint_name, endpoint = endpoint_cells[0]
    require(endpoint_name == "mcu_hwdata25", "candidate: endpoint identity drift")
    attrs = endpoint.get("attributes", {})
    require(attrs.get("NEXTPNR_BEL") == route_contract["candidate_endpoint_bel"], "candidate: endpoint BEL drift")
    require(attrs.get("AGRV2K_MCU_ENDPOINT_INTERFACE") == "HWDATA", "candidate: endpoint interface drift")
    require(int(attrs.get("AGRV2K_MCU_ENDPOINT_LANE", ""), 2) == 25, "candidate: endpoint lane drift")
    require(attrs.get("AGRV2K_MCU_ENDPOINT_MODE") == "DIRECT_FABRIC_INPUT", "candidate: endpoint mode drift")
    require(attrs.get("AGRV2K_MCU_ENDPOINT_VERSION") == "0" * 31 + "1", "candidate: endpoint version drift")
    endpoint_bits = endpoint.get("connections", {}).get("DIN")
    require(isinstance(endpoint_bits, list) and len(endpoint_bits) == 1, "candidate: endpoint DIN bit drift")
    endpoint_bit = endpoint_bits[0]

    sink = candidate_cells.get(route_contract["candidate_sink"]["cell"])
    require(isinstance(sink, dict) and sink.get("type") == "GENERIC_SLICE", "candidate: exact ordinary sink missing")
    require(sink.get("attributes", {}).get("NEXTPNR_BEL") == route_contract["candidate_sink"]["bel"], "candidate: sink BEL drift")
    require(sink.get("parameters", {}).get("INIT") == "1010101010101010", "candidate: sink is not the frozen identity LUT")
    require(sink.get("parameters", {}).get("FF_USED") == "0", "candidate: sink unexpectedly registered")
    require(sink.get("connections", {}).get("I", []).count(endpoint_bit) == 1, "candidate: endpoint bit must reach sink I exactly once")

    occurrences: list[tuple[str, str]] = []
    for cell_name, cell in candidate_cells.items():
        for port_name, bits in cell.get("connections", {}).items():
            if isinstance(bits, list) and endpoint_bit in bits:
                occurrences.extend((cell_name, port_name) for _ in range(bits.count(endpoint_bit)))
    require(
        sorted(occurrences) == sorted([(endpoint_name, "DIN"), (route_contract["candidate_sink"]["cell"], "I")]),
        f"candidate: hidden or duplicate endpoint consumer: {occurrences}",
    )

    endpoint_net = candidate.get("netnames", {}).get("hwdata25")
    require(isinstance(endpoint_net, dict) and endpoint_net.get("bits") == [endpoint_bit], "candidate: endpoint net drift")
    root, edges, _ = routing(endpoint_net, "candidate endpoint")
    endpoint_path = walk_route(root, edges, "candidate endpoint")
    require(endpoint_path[:2] == route_contract["candidate_first_hop"], "candidate: mandatory first hop drift")
    require(endpoint_path[-1] == route_contract["candidate_sink"]["wire"], "candidate: route does not terminate at exact sink wire")

    require(
        not any(cell.get("type") == "MCU_DIN" for cell in control_cells.values()),
        "control: MCU endpoint must be absent",
    )
    for cell in control_cells.values():
        attrs = cell.get("attributes", {})
        require(
            not any(key.startswith("AGRV2K_MCU_ENDPOINT_") for key in attrs),
            "control: endpoint authority attribute must be absent",
        )
    constant = control_cells.get("constant_low")
    require(isinstance(constant, dict), "control: constant_low cell missing")
    require(constant.get("attributes", {}).get("NEXTPNR_BEL") == route_contract["candidate_sink"]["bel"], "control: retained sink BEL drift")
    require(constant.get("parameters", {}).get("INIT") == "0000000000000000", "control: LUT must be constant-low")

    candidate_observed = candidate.get("netnames", {}).get("observed_lut")
    control_observed = control.get("netnames", {}).get("observed_lut")
    require(isinstance(candidate_observed, dict) and isinstance(control_observed, dict), "observation route missing")
    require(
        candidate_observed.get("attributes", {}).get("ROUTING")
        == control_observed.get("attributes", {}).get("ROUTING"),
        "candidate/control observation route differs",
    )
    observed_root, observed_edges, _ = routing(candidate_observed, "observation")
    observed_path = walk_route(observed_root, observed_edges, "observation")
    require(" -> ".join(observed_path) == route_contract["observation_route"], "observation route contract drift")
    for label, design in (("candidate", candidate), ("control", control)):
        iobs = [cell for cell in design["cells"].values() if cell.get("type") == "GENERIC_IOB"]
        require(len(iobs) == 1, f"{label}: exact observation IOB required")
        require(iobs[0].get("attributes", {}).get("NEXTPNR_BEL") == route_contract["observation_bel"], f"{label}: observation BEL drift")


def audit_compression(manifest: dict[str, Any]) -> None:
    for role in ("candidate", "control"):
        full = (PACKAGE_DIR / "artifacts" / f"{role}.bin").read_bytes()
        compressed = (PACKAGE_DIR / "artifacts" / f"{role}.bin.comp").read_bytes()
        require(len(full) >= 8 and len(compressed) >= 8, f"{role}: image header missing")
        require(full[:8] == compressed[:8], f"{role}: compressed header drift")
        require(full[:8].hex() == "402000010000ffff", f"{role}: unexpected device header")
        require(compressed[:8] + decode(compressed[8:]) == full, f"{role}: compressed image does not decode exactly")
        require(full[:8] + encode(full[8:]) == compressed, f"{role}: compressed image does not re-encode exactly")
    prereg = manifest["preregistration"]
    require(prereg["sha256"] == sha256(PACKAGE_DIR / prereg["path"]), "preregistration SHA-256 drift")


def audit_preregistration(manifest: dict[str, Any], prereg: dict[str, Any]) -> None:
    capture = prereg["capture"]
    require(capture == {
        "command": "CAP8 8 32768 20000000",
        "logical_mapping": "logical = raw & 0x01 (GP8 / L48 PIN_18)",
        "rate_hz": 20000000,
        "samples": EXPECTED_SAMPLES,
    }, "capture preregistration drift")
    requirements = prereg["classifier"]["candidate_positive_requirements"]
    require(requirements == {
        "complete_high_runs_minimum": COMPLETE_HIGH_RUNS_MIN,
        "complete_low_runs_minimum": COMPLETE_LOW_RUNS_MIN,
        "complete_run_length_samples": [RUN_LENGTH_MIN, RUN_LENGTH_MAX],
        "high_fraction_open_interval": [HIGH_FRACTION_MIN, HIGH_FRACTION_MAX],
        "transitions_minimum": TRANSITIONS_MIN,
    }, "classifier constants disagree with preregistration")
    safety = prereg["safety"]
    require(safety == {
        "automatic_retry": False,
        "board_lock_required": True,
        "control_restore_required": True,
        "flash_writes": 0,
        "hart_halted_after_recovery": True,
        "option_byte_changes": 0,
        "pico_gp8_role": "input-only observer",
        "por_or_power_cycle": False,
        "raw_evidence_sealed_before_interpretation": True,
        "rewiring": False,
        "transport_handles_closed": True,
    }, "safety preregistration drift")
    require(manifest.get("hardware_execution_authorized_by_this_manifest") is False, "desk manifest must not authorize hardware")
    exact = prereg["exact_inputs"]
    for role in ("candidate", "control"):
        key = f"{role}_image"
        artifact = manifest["artifacts"][f"{role}.bin"]
        require(exact[key]["sha256"] == artifact["sha256"] and exact[key]["size"] == artifact["size"], f"{role}: preregistered image drift")
    firmware = manifest["artifacts"]["stimulus.bin"]
    require(exact["stimulus_binary"]["sha256"] == firmware["sha256"] and exact["stimulus_binary"]["size"] == firmware["size"], "stimulus preregistration drift")


def audit_git(manifest: dict[str, Any], require_clean: bool) -> None:
    identity = manifest["compiler_identity"]
    commit = identity["commit"]
    require(git("cat-file", "-t", commit) == "commit", "compiler commit is unavailable")
    require(git("rev-parse", f"{commit}^{{tree}}") == identity["tree"], "compiler tree drift")
    require(git("rev-parse", f"{commit}^") == identity["parent"], "compiler parent drift")
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO_ROOT, check=False
    )
    require(completed.returncode == 0, "accepted compiler commit is not an ancestor of HEAD")
    text_paths = [
        PACKAGE_DIR / "package_manifest.json",
        PACKAGE_DIR / "preregistration.json",
        *(PACKAGE_DIR / name for name in manifest["sources"]),
        PACKAGE_DIR / "artifacts" / "candidate_routed.json",
        PACKAGE_DIR / "artifacts" / "control_routed.json",
    ]
    for path in text_paths:
        relative = path.relative_to(REPO_ROOT).as_posix()
        require(git("check-attr", "eol", "--", relative).endswith("eol: lf"), f"{relative}: checkout EOL is not pinned to LF")
    binary_paths = [
        PACKAGE_DIR / "artifacts" / name
        for name in manifest["artifacts"]
        if not name.endswith(".json")
    ]
    for path in binary_paths:
        relative = path.relative_to(REPO_ROOT).as_posix()
        require(git("check-attr", "text", "--", relative).endswith("text: unset"), f"{relative}: artifact is not pinned binary")
    git("diff", "--check")
    if require_clean:
        require(git("status", "--porcelain=v1") == "", "worktree is not clean")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        manifest = load_json(PACKAGE_DIR / "package_manifest.json")
        prereg = load_json(PACKAGE_DIR / "preregistration.json")
        require(manifest.get("id") == "N58-HWDATA25-HIL-S01-DESK-V1-20260828", "manifest identity drift")
        audit_file_table(manifest["artifacts"], PACKAGE_DIR / "artifacts", "artifacts")
        audit_file_table(manifest["sources"], PACKAGE_DIR, "sources")
        audit_compression(manifest)
        audit_routes(manifest)
        audit_preregistration(manifest, prereg)
        audit_git(manifest, args.require_clean)
    except (AuditError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"REJECT: {exc}", file=sys.stderr)
        return 1
    print("PASS_DESK_ONLY")
    print(f"manifest_id={manifest['id']}")
    print(f"compiler_commit={manifest['compiler_identity']['commit']}")
    print(f"candidate_sha256={manifest['artifacts']['candidate.bin']['sha256']}")
    print(f"control_sha256={manifest['artifacts']['control.bin']['sha256']}")
    print("hardware_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
