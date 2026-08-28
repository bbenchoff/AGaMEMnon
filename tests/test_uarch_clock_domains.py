"""Typed whole-device GCLK0 closure and retained VP-AGM-007 evidence."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
WITNESS = ROOT / "agamemnon" / "chipdb" / "clock_reach_silicon_negative.csv"


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_clock_reach_table_is_exactly_the_four_witnessed_negative_sites():
    rows = list(csv.DictReader(WITNESS.open(encoding="utf-8", newline="")))
    assert {(int(row["x"]), int(row["y"])) for row in rows} == {
        (12, 4), (14, 5), (20, 12), (20, 1),
    }
    assert len(rows) == 4
    assert all(row["clock_domain"] == "GCLK0" for row in rows)
    assert all(row["sysclk_mhz"] == "100" and row["hse_mhz"] == "8" for row in rows)
    assert all(row["defect"] == "VP-AGM-007" for row in rows)
    assert all(row["observations"] == "3" for row in rows)
    assert all(row["provenance"] == "retained_sram_zero_state" for row in rows)
    assert (1, 1) not in {(int(row["x"]), int(row["y"])) for row in rows}


def test_clock_reach_witness_is_retained_as_evidence_not_runtime_legality():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    clocks = (ROOT / "agamemnon" / "engine" / "features" / "clocks.py").read_text(
        encoding="utf-8"
    )
    runtime = _between(cli, "runtime_assets = (", "emit_context =")
    assert '"clock_reach_silicon_negative.csv"' not in runtime
    assert "runtime_asset, hashlib.sha256" in cli
    assert "shutil.copy(src_asset, devdb)" in cli
    assert '"clock_reach_silicon_negative.csv"' in clocks
    assert "refuse_silicon_negative_clock_reach" in clocks
    source = UARCH.read_text(encoding="utf-8")
    assert "load_clock_domain_reach" not in source
    assert "clock_domains_reach" not in source


def test_whole_device_owner_uses_active_clock_connections_not_cell_names():
    source = UARCH.read_text(encoding="utf-8")
    owner = _between(
        source,
        "void refresh_global_clock_owner",
        "void append_expected_clock_pip",
    )
    assert "shared_clock_requirement(ctx, cell)" in owner
    assert "requirement.active()" in owner
    assert "add_global_clock_net(requirement.clock" in owner
    assert "global_clock_owner->driver.cell" in owner
    assert "source->admitted" in owner
    assert "cell->name" not in owner


def test_typed_gclk0_is_whole_device_legality_and_route_closure():
    source = UARCH.read_text(encoding="utf-8")
    validity = _between(
        source,
        "bool isBelLocationValid(BelId bel, bool explain_invalid) const override",
        "\n    }\n};",
    )
    assert "global_clock_cell_compatible(ci, explain_invalid)" in validity
    assert "refresh_global_clock_resources(\"end-pack\", true)" in source
    assert "audit_global_clock_routes(\"end-pack import\", false)" in source
    assert "lock_global_clock_tree(\"end-pack\")" in source
    assert "refresh_global_clock_resources(\"pre-route\", true)" in source
    assert "audit_global_clock_routes(\"post-route\", true)" in source
    assert "global_clock_pip_legal(pip, net)" in source
