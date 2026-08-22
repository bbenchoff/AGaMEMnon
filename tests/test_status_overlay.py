"""Fail-closed contract for the ordinary-Verilog public32 status overlay."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agamemnon.engine import status_overlay as so
from tools import generate_status_overlay_devdb as devdb_generator


ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "qualification"
OVERLAY = Q / "mcu_ahb_status_overlay_pulse_checkpoint.json"
PRODUCTION = Q / "mcu_ahb_status_overlay_pulse_public32_routed.json"
ZERO = Q / "mcu_ahb_status_overlay_zero_control_public32_routed.json"
LEDGER = Q / "mcu_ahb_status_overlay_pulse_evidence.jsonl"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path=OVERLAY):
    return json.loads(path.read_text(encoding="utf-8"))


def write(tmp_path, design, name="mutated.json"):
    path = tmp_path / name
    path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    return path


def reject(tmp_path, design, match):
    with pytest.raises(so.StatusOverlayError, match=match):
        so.compose(write(tmp_path, design))


def test_release_compositor_reproduces_the_pinned_checkpoint(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    report = so.compose_files(OVERLAY, first)
    so.compose_files(OVERLAY, second)
    assert first.read_bytes() == second.read_bytes() == PRODUCTION.read_bytes()
    assert sha(OVERLAY) == \
        "16c8b93bab28636a8115bc095cee327e5f2e9a3ee40df5566f6816659a094bcd"
    assert sha(PRODUCTION) == \
        "4d93287eb085d6e48af9c15486e42398f548a447e2a4fb9e0dc3cb895c5de28f"
    assert sha(ZERO) == \
        "21f320785b8fe32d95c4e5650bf979ce4c076bb9f1b49dead984900205d99c9f"
    assert report == {
        "schema": 1,
        "core_sha256": so.CORE_SHA256,
        "overlay_sha256": sha(OVERLAY),
        "output_sha256": sha(PRODUCTION),
        "user_cells": 4,
        "user_routed_nets": 4,
        "event_net": "user_status$status_set",
        "event_sink": "X17Y11_IMUX56",
        "scope": "one scalar, pure-fabric, separately routed synchronous status event",
    }


def test_composition_changes_only_the_reviewed_core_cone():
    base = load(so.DEFAULT_CORE)["modules"]["top"]
    candidate = load(PRODUCTION)["modules"]["top"]
    common_cells = set(base["cells"]) & set(candidate["cells"])
    assert {name for name in common_cells
            if base["cells"][name] != candidate["cells"][name]} == {
                "public_set_event"}
    common_nets = set(base["netnames"]) & set(candidate["netnames"])
    assert {name for name in common_nets
            if base["netnames"][name] != candidate["netnames"][name]} == {
                "hclk", "hwdata[1]", "public_status_pending"}
    assert set(candidate["netnames"]) - set(base["netnames"]) == {
        "user_status$" + name for name in (
            "$PACKER_VCC_NET", "started", "delayed", "status_set")}
    before_hw = so.route_items(base["netnames"]["hwdata[1]"]["attributes"]["ROUTING"])
    after_hw = so.route_items(candidate["netnames"]["hwdata[1]"]["attributes"]["ROUTING"])
    before_pending = so.route_items(
        base["netnames"]["public_status_pending"]["attributes"]["ROUTING"])
    after_pending = so.route_items(
        candidate["netnames"]["public_status_pending"]["attributes"]["ROUTING"])
    assert {item[0] for item in before_hw} - {item[0] for item in after_hw} == \
        so.HW_REMOVED
    assert {item[0] for item in before_pending} - \
        {item[0] for item in after_pending} == so.PENDING_REMOVED
    setter = candidate["cells"]["public_set_event"]
    assert setter["parameters"]["INIT"] == "1010101010101010"
    assert setter["connections"]["I"][1:] == ["0", "0", "0"]
    assert candidate["netnames"]["user_status$status_set"]["bits"] == \
        [setter["connections"]["I"][0]]


def test_rejects_bad_port_shapes_and_forbidden_hard_cells(tmp_path):
    design = load()
    design["modules"]["top"]["ports"]["extra"] = {
        "direction": "input", "bits": [999999]}
    reject(tmp_path, design, "exactly one scalar output")
    design = load()
    cell = next(iter(design["modules"]["top"]["cells"].values()))
    cell["type"] = "ALTA_BRAM9K"
    reject(tmp_path, design, "forbidden hard cell")


def test_rejects_unplaced_duplicate_and_core_bels(tmp_path):
    design = load()
    cells = design["modules"]["top"]["cells"]
    fabric = [cell for cell in cells.values() if cell["type"] == "GENERIC_SLICE"]
    fabric[0]["attributes"].pop("NEXTPNR_BEL")
    reject(tmp_path, design, "unplaced user cell")
    design = load()
    cells = design["modules"]["top"]["cells"]
    fabric = [cell for cell in cells.values() if cell["type"] == "GENERIC_SLICE"]
    fabric[1]["attributes"]["NEXTPNR_BEL"] = \
        fabric[0]["attributes"]["NEXTPNR_BEL"]
    reject(tmp_path, design, "duplicate user BEL")
    design = load()
    cells = design["modules"]["top"]["cells"]
    fabric = next(cell for cell in cells.values() if cell["type"] == "GENERIC_SLICE")
    core = load(so.DEFAULT_CORE)["modules"]["top"]
    fabric["attributes"]["NEXTPNR_BEL"] = \
        core["cells"]["public_set_event"]["attributes"]["NEXTPNR_BEL"]
    reject(tmp_path, design, "qualified-core BEL")


def test_rejects_incomplete_and_colliding_routes(tmp_path):
    design = load()
    design["modules"]["top"]["netnames"]["started"]["attributes"]["ROUTING"] = \
        "X8Y2_OMUX14;;1"
    reject(tmp_path, design, "not completely routed")

    # A disconnected alias is still physical state: it may not steal a route
    # wire from another user net or from the qualified core.
    design = load()
    top = design["modules"]["top"]
    top["netnames"]["collision"] = copy.deepcopy(top["netnames"]["status_set"])
    top["netnames"]["collision"]["bits"] = [999998]
    reject(tmp_path, design, "routing wire collision")

    design = load()
    top = design["modules"]["top"]
    core = load(so.DEFAULT_CORE)["modules"]["top"]
    occupied = next(iter(so._route_owners(core)))
    top["netnames"]["core_collision"] = {
        "hide_name": 1, "bits": [999997],
        "attributes": {"ROUTING": occupied + ";;1"},
    }
    reject(tmp_path, design, "routing wire collision")


def test_rejects_nonqualified_clock_root(tmp_path):
    design = load()
    route = so.route_items(
        design["modules"]["top"]["netnames"]["clk"]["attributes"]["ROUTING"])
    route = [("GCLK1", "", strength) if not pip else (dst, pip, strength)
             for dst, pip, strength in route]
    design["modules"]["top"]["netnames"]["clk"]["attributes"]["ROUTING"] = \
        so.encode_route(route)
    reject(tmp_path, design, "not rooted at qualified GCLK0")


def test_rejects_core_hash_and_exact_hook_shape_drift(tmp_path, monkeypatch):
    core = load(so.DEFAULT_CORE)
    core_path = write(tmp_path, core, "core-comment.json")
    # Make a semantic no-op byte drift explicitly.  json.dumps happens to
    # reproduce the canonical LF source byte-for-byte on POSIX, while Windows
    # historically introduced CRLF here as an accidental mutation.
    core_path.write_bytes(core_path.read_bytes() + b" ")
    with pytest.raises(so.StatusOverlayError, match="core hash drifted"):
        so.compose(OVERLAY, core_path=core_path)

    core = load(so.DEFAULT_CORE)
    top = core["modules"]["top"]
    items = so.route_items(top["netnames"]["hwdata[1]"]["attributes"]["ROUTING"])
    top["netnames"]["hwdata[1]"]["attributes"]["ROUTING"] = so.encode_route(
        [item for item in items if item[0] != "X14Y10_RMUX31"])
    core_path = write(tmp_path, core, "core-route-drift.json")
    monkeypatch.setattr(so, "CORE_SHA256", sha(core_path))
    with pytest.raises(so.StatusOverlayError,
                       match="qualified set-hook route shape drifted"):
        so.compose(OVERLAY, core_path=core_path)


def test_zero_control_changes_only_the_user_event_lut():
    production = load(PRODUCTION)["modules"]["top"]
    control = load(ZERO)["modules"]["top"]
    assert production["netnames"] == control["netnames"]
    changed = {name for name in production["cells"]
               if production["cells"][name] != control["cells"][name]}
    assert len(changed) == 1
    name = changed.pop()
    assert name.startswith(so.PREFIX)
    assert production["cells"][name]["parameters"]["INIT"] == \
        "0100010001000100"
    assert control["cells"][name]["parameters"]["INIT"] == "0" * 16


def test_qualification_control_composer_reproduces_both_images(tmp_path):
    script = Q / "compose_mcu_ahb_status_overlay_pulse.py"
    production, zero = tmp_path / "production.json", tmp_path / "zero.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env.get("PYTHONPATH", "")]
    )
    subprocess.run([sys.executable, str(script), "--out", str(production)],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    subprocess.run([sys.executable, str(script), "--zero-control", "--out", str(zero)],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    assert production.read_bytes() == PRODUCTION.read_bytes()
    assert zero.read_bytes() == ZERO.read_bytes()


def test_pack_manifest_and_silicon_record_bind_the_causal_matrix():
    manifest = json.loads((Q / "pack_regression.json").read_text(encoding="utf-8"))
    rows = {row["routed"]: row for row in manifest["artifacts"]}
    assert rows["qualification/mcu_ahb_status_overlay_pulse_public32_routed.json"] == {
        "routed": "qualification/mcu_ahb_status_overlay_pulse_public32_routed.json",
        "routed_sha256": sha(PRODUCTION),
        "bitstream_sha256":
            "a9a10e81aff23afa512445ffacb18eb446283eeb8f0dc2152aa4c7f704652baf",
        "environment": {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"},
    }
    assert rows[
        "qualification/mcu_ahb_status_overlay_zero_control_public32_routed.json"
    ]["bitstream_sha256"] == \
        "8a562b8563b607193e026184ed0da9cb9828e476d1621eda11ac08aa1da84bec"

    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    assert record["result"] == "pass_generic_routed_status_overlay_one_shot_w1c"
    assert record["runs"] == {"negative": 1, "zero_control": 1, "production": 3}
    assert record["hardware"] is True and record["flash_written"] is False
    assert record["core_routed_sha256"] == so.CORE_SHA256
    assert record["overlay_routed_sha256"] == sha(OVERLAY)
    assert record["production_routed_sha256"] == sha(PRODUCTION)
    assert record["zero_control_routed_sha256"] == sha(ZERO)
    assert record["pack"]["unmapped"] == record["pack"]["predicted"] == \
        record["pack"]["legacy_absolute"] == 0
    logs = {
        "negative": Q / "mcu_ahb_status_overlay_negative_openocd.log",
        "zero_control": Q / "mcu_ahb_status_overlay_zero_control_openocd.log",
        "production": [Q / f"mcu_ahb_status_overlay_pulse_openocd_run{i}.log"
                       for i in (1, 2, 3)],
    }
    def canonical(path):
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")
                              .replace(b"\r", b"\n")).hexdigest()
    assert record["silicon_log_hashes"] == {
        "negative": canonical(logs["negative"]),
        "zero_control": canonical(logs["zero_control"]),
        "production": [canonical(path) for path in logs["production"]],
    }
    assert "not every possible user design" in record["scope"]
    assert "not placement reservation" in record["scope"]


def test_fixture_contains_no_machine_specific_path():
    text = OVERLAY.read_text(encoding="utf-8")
    windows_home = "C:" + "/Users/"
    escaped_home = "C:" + "\\\\Users\\\\"
    assert windows_home not in text and escaped_home not in text
    assert "agamemnon/synth/cells_map.v" in text


def test_bundled_strict_device_snapshot_is_hash_bound_and_fail_closed(
        tmp_path, monkeypatch):
    manifest = json.loads(so.DEVDB_MANIFEST.read_text(encoding="utf-8"))
    assert hashlib.sha256(so.DEVDB_MANIFEST.read_bytes()).hexdigest() == \
        so.DEVDB_MANIFEST_SHA256
    assert so.DEFAULT_DEVDB is None
    assert set(manifest["tables"]) == {"dev_pips.csv", "dev_belpins.csv"}
    for row in manifest["tables"].values():
        artifact = so.DEVDB_MANIFEST.parent / row["artifact"]
        compressed = artifact.read_bytes()
        raw = gzip.decompress(compressed)
        assert hashlib.sha256(compressed).hexdigest() == row["artifact_sha256"]
        assert hashlib.sha256(raw).hexdigest() == row["source_sha256"]
        assert len(raw) == row["source_bytes"]

    for row in manifest["tables"].values():
        source = so.DEVDB_MANIFEST.parent / row["artifact"]
        (tmp_path / row["artifact"]).write_bytes(source.read_bytes())
    pips = tmp_path / manifest["tables"]["dev_pips.csv"]["artifact"]
    corrupted = bytearray(pips.read_bytes())
    corrupted[-1] ^= 1
    pips.write_bytes(corrupted)
    broken_path = tmp_path / "manifest.json"
    broken_path.write_bytes(so.DEVDB_MANIFEST.read_bytes())
    so._shipped_table.cache_clear()
    monkeypatch.setattr(so, "DEVDB_MANIFEST", broken_path)
    with pytest.raises(so.StatusOverlayError, match="table hash drifted"):
        so._shipped_table("dev_pips.csv")
    so._shipped_table.cache_clear()


def _reconstruct_pinned_devdb_strict(tmp_path):
    """Rebuild the two canonical devdb_strict inputs from the checked-in,
    hash-pinned snapshot (``DEVDB_MANIFEST_SHA256`` in status_overlay.py).
    This is the frozen, version-controlled source of truth: unlike the live
    ``agamemnon/engine/uarch/agrv2k/devdb_strict/`` build directory -- which
    is gitignored and continuously regenerated by ad hoc nextpnr uarch /
    conduction-qualification work with no commit tying it to a particular
    freeze -- it is identical on every machine and every run.
    """
    source = tmp_path / "devdb_strict"
    source.mkdir()
    manifest = json.loads(so.DEVDB_MANIFEST.read_text(encoding="utf-8"))
    for name, row in manifest["tables"].items():
        compressed = (so.DEVDB_MANIFEST.parent / row["artifact"]).read_bytes()
        (source / name).write_bytes(gzip.decompress(compressed))
    return source


def test_bundled_strict_device_snapshot_is_mechanically_reproducible(tmp_path):
    # This test used to read the live agrv2k/devdb_strict/ build directory
    # whenever it happened to exist on disk, and only fell back to the
    # pinned snapshot when it was absent. That made "mechanically
    # reproducible" depend on ambient, shared, mutable machine state: that
    # directory is gitignored and gets rebuilt by ongoing conduction/edge
    # -qualification work independent of any "freeze the shipped snapshot"
    # commit, so the test passed or failed depending on whether a background
    # build happened to still agree with the last freeze -- not on whether
    # the generator itself was deterministic. Root cause confirmed: calling
    # devdb_generator.generate() twice back-to-back on the SAME input is
    # always byte-identical (the gzip/manifest emitter is deterministic --
    # fixed mtime=0, fixed compresslevel, fixed table order, fixed JSON
    # formatting); the failures came entirely from the live devdb_strict
    # directory having moved past the last committed freeze.
    #
    # The hermetic, environment-independent claim this test name makes is
    # therefore checked against the pinned snapshot only, and by actually
    # running the generator twice.
    pinned_source = _reconstruct_pinned_devdb_strict(tmp_path)
    expected = {
        "status_overlay_dev_pips.csv.gz",
        "status_overlay_dev_belpins.csv.gz",
        "status_overlay_devdb_manifest.json",
    }
    first = tmp_path / "generated_first"
    second = tmp_path / "generated_second"
    devdb_generator.generate(pinned_source, first)
    devdb_generator.generate(pinned_source, second)
    for output in (first, second):
        assert {path.name for path in output.iterdir()} == expected
    for name in expected:
        first_bytes = (first / name).read_bytes()
        assert first_bytes == (second / name).read_bytes(), (
            "generator is not byte-deterministic on identical pinned input"
        )
        assert first_bytes == (so.DEVDB_MANIFEST.parent / name).read_bytes(), (
            "generator output drifted from the committed frozen artifact "
            "even though the pinned canonical inputs did not change"
        )

    # Supplementary, non-flaky coverage: if a live nextpnr uarch build also
    # happens to be present in this checkout, the generator must still be
    # deterministic and internally hash-consistent on it. It is legitimately
    # NOT required to match the frozen snapshot above -- that directory
    # moves independently of any freeze commit -- so equality to a
    # point-in-time snapshot is deliberately not asserted here.
    live_source = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
    if all((live_source / name).is_file() for name in devdb_generator.TABLES):
        live_first = tmp_path / "live_first"
        live_second = tmp_path / "live_second"
        devdb_generator.generate(live_source, live_first)
        devdb_generator.generate(live_source, live_second)
        manifest = json.loads(
            (live_first / "status_overlay_devdb_manifest.json")
            .read_text(encoding="utf-8")
        )
        for name in devdb_generator.TABLES:
            artifact = f"status_overlay_{name}.gz"
            live_bytes = (live_first / artifact).read_bytes()
            assert live_bytes == (live_second / artifact).read_bytes(), (
                "generator is not byte-deterministic on identical live input"
            )
            raw = (live_source / name).read_bytes() \
                .replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            row = manifest["tables"][name]
            assert row["source_sha256"] == hashlib.sha256(raw).hexdigest()
            assert gzip.decompress(live_bytes) == raw
