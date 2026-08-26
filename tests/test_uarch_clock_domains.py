"""Witness-bounded clock domains and placement legality for VP-AGM-007."""

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


def test_clock_reach_witness_is_fingerprinted_owned_and_copied_to_devdb():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    clocks = (ROOT / "agamemnon" / "engine" / "features" / "clocks.py").read_text(
        encoding="utf-8"
    )
    runtime = _between(cli, "runtime_assets = (", "emit_context =")
    assert '"clock_reach_silicon_negative.csv"' in runtime
    assert "runtime_asset, hashlib.sha256" in cli
    assert "shutil.copy(src_asset, devdb)" in cli
    assert '"clock_reach_silicon_negative.csv"' in clocks


def test_get_clock_domains_uses_an_active_ff_clock_not_a_cell_name():
    source = UARCH.read_text(encoding="utf-8")
    domains = _between(source, "std::set<IdString> getClockDomains", "bool clock_domains_reach")
    assert 'cell->type != ctx->id("GENERIC_SLICE")' in domains
    assert 'ctx->id("FF_USED")' in domains
    assert 'cell->ports.find(ctx->id("CLK"))' in domains
    assert "clock->second.net != nullptr" in domains
    assert 'domains.insert(ctx->id("GCLK0"))' in domains
    assert "VP-AGM-007" not in domains


def test_silicon_negative_domain_reach_is_a_placement_legality_refusal():
    source = UARCH.read_text(encoding="utf-8")
    reach = _between(source, "bool clock_domains_reach", "// ---- routing gate")
    validity = _between(
        source,
        "bool isBelLocationValid(BelId bel, bool explain_invalid) const override",
        "\n    }\n};",
    )
    assert "row.sysclk_mhz != active_sysclk_mhz" in reach
    assert "row.hse_mhz != active_hse_mhz" in reach
    assert "!domains.count(row.domain)" in reach
    assert "return false;" in reach
    assert "getClockDomains(ci)" in validity
    assert "clock_domains_reach(clock_domains, ci, bel, explain_invalid)" in validity
    assert validity.index("clock_domains_reach") < validity.index("fixed_endpoint_pins_reachable")
