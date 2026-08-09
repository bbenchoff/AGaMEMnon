import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from agamemnon.engine import bram_emit
from agamemnon.engine.features.bram import BramFeature
from agamemnon.engine.registry import options_from


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "agamemnon/chipdb/bram_config_admission.json"
PIPS = ROOT / "agamemnon/engine/pips_bram_pll.csv"


def test_bram_config_metadata_retains_all_39_reviewed_rows():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["schema"] == "agamemnon.bram-config-encoding-metadata.v1"
    assert value["claim"] == "config-encoding-only"
    assert value["source_admission_manifest_sha256"] == \
        "1c7f6edc86bf0caf8f6abfc1356d00770c34aae0f8e17c7962e3bd129ae6d628"
    assert value["accounting"] == {
        "admitted_rows": 39,
        "execution_exclusions": 0,
        "preexisting_exceptions": 15,
    }
    assert value["permission"] == {
        "allowed": "experimental-strict",
        "default_selection": "denied",
        "release_strict": "denied",
    }
    rows = value["rows"]
    assert len(rows) == 39 and len({row["target_id"] for row in rows}) == 39
    assert all(row["registry_maturity"] == "experimental"
               and row["evidence_tier"] == "differentially_validated"
               and row["claim_domain"] == "config-encoding"
               and row["strict_permission"] == "experimental-strict"
               and row["scope"]["behavior"] == "not-established"
               and row["scope"]["silicon"] == "not-exercised"
               for row in rows)
    assert "vendor" not in MANIFEST.read_text(encoding="utf-8").lower()


def test_bram_config_metadata_names_exact_population_and_selector_contracts():
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))["rows"]
    populations = {}
    for row in rows:
        populations[row["parameter"]] = populations.get(row["parameter"], 0) + 1
        if "physical_mux_selectors" in row:
            encoded = json.dumps(row["physical_mux_selectors"],
                                 separators=(",", ":")).encode("utf-8")
            assert len(row["physical_mux_selectors"]) == row["selector_count"]
            assert hashlib.sha256(encoded).hexdigest() == row["selector_set_sha256"]
        else:
            assert row["parameter"] == "INIT_VAL"
            assert row["selector_representation"] == "explicit-set-digest"
            assert row["selector_count"] == 4864
    assert populations == {
        "CLKMODE": 3, "DLYTIME": 3, "INIT_VAL": 9, "PACKEDMODE": 1,
        "PORTA_CLKIN_EN": 1, "PORTA_CLKOUT_EN": 1, "PORTA_OUTREG": 1,
        "PORTA_RSTIN_EN": 1, "PORTA_WIDTH": 5, "PORTA_WRITETHRU": 1,
        "PORTB_CLKIN_EN": 1, "PORTB_CLKOUT_EN": 1, "PORTB_OUTREG": 1,
        "PORTB_RSTIN_EN": 1, "PORTB_RSTOUT_EN": 1, "PORTB_WIDTH": 5,
        "PORTB_WRITETHRU": 1, "RSEN_DLY": 2,
    }


def test_executable_experimental_encodings_match_independent_admission_rows():
    """Bind executable constants to the reviewed metadata without reusing them."""
    cases = {
        ("PACKEDMODE", "1"): ("CFG_PACKEDMODE[0]",),
        ("DLYTIME", "01"): ("CFG_DLYTIME[0]",),
        ("DLYTIME", "10"): ("CFG_DLYTIME[1]",),
        ("DLYTIME", "11"): ("CFG_DLYTIME[0]", "CFG_DLYTIME[1]"),
        ("PORTA_OUTREG", "1"): ("CFG_SELOUT_A[0]",),
        ("PORTB_OUTREG", "1"): ("CFG_SELOUT_B[0]",),
        ("PORTA_WRITETHRU", "1"): ("CFG_SEL_WRITHU_A[0]",),
        ("PORTB_WRITETHRU", "1"): ("CFG_SEL_WRITHU_B[0]",),
        ("RSEN_DLY", "01"): ("CFG_RSEN_DLY[0]",),
        ("RSEN_DLY", "10"): ("CFG_RSEN_DLY[1]",),
        ("PORTA_WIDTH", "10000"): ("CFG_DWSEL_A[4]",),
        ("PORTB_WIDTH", "10000"): ("CFG_DWSEL_B[4]",),
    }
    field_names = {
        "PACKEDMODE", "DLYTIME", "PORTA_OUTREG", "PORTB_OUTREG",
        "PORTA_WRITETHRU", "PORTB_WRITETHRU", "RSEN_DLY",
    }
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))["rows"]
    admitted = {
        (row["parameter"], row["legal_value"]):
            tuple(row["physical_mux_selectors"])
        for row in rows
        if row["parameter"] in field_names
        or (row["parameter"] in {"PORTA_WIDTH", "PORTB_WIDTH"}
            and row["legal_value"] == "10000")
    }
    assert admitted == cases
    assert ("RSEN_DLY", "11") not in admitted

    # These explicit legal sets ensure a newly executable value cannot escape
    # this manifest binding merely by being added to the emitter's constants.
    expected_legal = {
        "PACKEDMODE": {0, 1}, "DLYTIME": {0, 1, 2, 3},
        "PORTA_OUTREG": {0, 1}, "PORTB_OUTREG": {0, 1},
        "PORTA_WRITETHRU": {0, 1}, "PORTB_WRITETHRU": {0, 1},
        "RSEN_DLY": {0, 1, 2},
    }
    assert set(bram_emit.EXPERIMENTAL_FIELDS) == set(expected_legal)
    assert {
        name: set(contract[2])
        for name, contract in bram_emit.EXPERIMENTAL_FIELDS.items()
    } == expected_legal
    assert bram_emit.EXPERIMENTAL_DIRECT_WIDTH_CODES == {0b10000}

    def physical(selector):
        match = re.fullmatch(r"([A-Z0-9_]+)\[(\d+)]", selector)
        assert match
        return bram_emit.CELLS[(13, 4, match.group(1))][int(match.group(2))]

    for (parameter, legal_value), selectors in cases.items():
        value = int(legal_value, 2) if len(legal_value) > 1 else int(legal_value)
        fields = {} if parameter.endswith("_WIDTH") else {parameter: value}
        width_a = value if parameter == "PORTA_WIDTH" else 0
        width_b = value if parameter == "PORTB_WIDTH" else 0
        emitted = bram_emit.emit(
            13, 4, width_a, 0, 0, {}, width_b=width_b,
            experimental=fields, allow_experimental=True,
        )
        assert emitted == {physical(selector) for selector in selectors}


def test_all_39_admission_rows_emit_from_independent_csv_at_all_four_sites():
    """Exercise the 39-row JSON contract at Y1..Y4 without using CELLS."""
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))["rows"]
    cells = {}
    with PIPS.open(newline="", encoding="utf-8") as stream:
        for item in csv.DictReader(stream):
            cells[(int(item["x"]), int(item["y"]), item["mux"],
                   int(item["sel"]))] = (int(item["byte"]), int(item["mask"]))

    marker = 0
    marker_selectors = []
    for word_index in range(512):
        word = (0x155 << 9) | word_index
        marker |= word << (18 * word_index)
        marker_selectors.extend(
            "INIT_VAL[%d]" % (18 * word_index + bit)
            for bit in range(18) if word >> bit & 1
        )
    marker_encoded = json.dumps(marker_selectors,
                                separators=(",", ":")).encode("utf-8")
    assert len(marker_selectors) == 4864
    assert hashlib.sha256(marker_encoded).hexdigest() == \
        "aef41f27ae36fc94a85c8ed9597a9c1117e053c2e363ccbcb90635999a618508"

    experimental_fields = {
        "PACKEDMODE", "DLYTIME", "PORTA_OUTREG", "PORTB_OUTREG",
        "PORTA_WRITETHRU", "PORTB_WRITETHRU", "RSEN_DLY",
    }
    checks = 0
    for row in rows:
        parameter = row["parameter"]
        legal = row["legal_value"]
        selectors = (marker_selectors if parameter == "INIT_VAL" else
                     row["physical_mux_selectors"])
        assert len(selectors) == row["selector_count"]
        for y in (1, 2, 3, 4):
            width_a = int(legal, 2) if parameter == "PORTA_WIDTH" else 0
            width_b = int(legal, 2) if parameter == "PORTB_WIDTH" else 0
            clkmode = int(legal, 2) if parameter == "CLKMODE" else 0
            init_value = marker if parameter == "INIT_VAL" else 0
            enables = ({parameter: 1} if parameter.startswith("PORT")
                       and parameter.endswith("_EN") else {})
            experimental = ({parameter: int(legal, 2)}
                            if parameter in experimental_fields else {})
            emitted = bram_emit.emit(
                13, y, width_a, clkmode, init_value, enables,
                width_b=width_b, experimental=experimental,
                allow_experimental=True,
            )
            expected = set()
            for selector in selectors:
                match = re.fullmatch(r"([A-Z0-9_]+)\[(\d+)]", selector)
                assert match
                expected.add(cells[(13, y, match.group(1), int(match.group(2)))])
            assert emitted == expected, (row["name"], y)
            checks += 1
    assert checks == 39 * 4


def test_runtime_experimental_policy_site_and_device_gates(tmp_path):
    feature = BramFeature()

    def module(site):
        return {"cells": {"bram": {
            "type": "ALTA_BRAM9K",
            "attributes": {"NEXTPNR_BEL": site},
            "parameters": {"PORTA_WIDTH": "10000"},
            "connections": {},
        }}}

    with pytest.raises(ValueError, match="AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG"):
        feature.prepare(module("X13Y4_BRAM"), tmp_path, options_from({}))
    with pytest.raises(ValueError, match="AGRV2KL48/L48"):
        feature.prepare(module("X13Y4_BRAM"), tmp_path, options_from({
            "AGAMEMNON_DEVICE": "AGRV2KL64",
            "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG": "1",
        }))
    with pytest.raises(ValueError, match="X13Y1..Y4"):
        feature.prepare(module("X12Y4_BRAM"), tmp_path, options_from({
            "AGAMEMNON_DEVICE": "AGRV2KL48",
            "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG": "1",
        }))
    accepted = feature.prepare(module("X13Y4_BRAM"), tmp_path, options_from({
        "AGAMEMNON_DEVICE": "AGRV2KL48",
        "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG": "1",
    }))
    assert accepted.cells == [(13, 4, 0b10000, 0, 0)]
