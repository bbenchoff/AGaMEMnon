"""Per-pad IO electrical attributes (measured CFG_PULL_UP / CFG_OPEN_DRAIN).

The bits live in the regenerated [0:164] preamble region and were isolated by
vendor ``set_config`` image differentials, with PIN_16 pull-up and PIN_26
open-drain witnessed on silicon (``qualification/fabric_io_electrical_evidence.jsonl``).
Emission must be fail-closed to the measured rows.
"""
import csv
from pathlib import Path

import pytest

from agamemnon.engine import agasc, preamble
from agamemnon.engine.features.physical_io import FEATURE, PhysicalIoState
from agamemnon.engine.registry import OPTIONS, EngineOptions


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
TABLE = CHIPDB / "io_pad_electrical_L48.csv"
# Silicon-witnessed anchors; every other row is encoding-only.
PIN16_PULLUP = (90, 1)
PIN26_OPEN_DRAIN = (10, 7)
# Special-function pad sites that took no CFG_PULL_UP through set_config.
NO_EFFECT_PADS = {
    "PIN_2", "PIN_10", "PIN_11", "PIN_12", "PIN_21",
    "PIN_32", "PIN_33", "PIN_34", "PIN_35", "PIN_45", "PIN_46",
}


def rows():
    with TABLE.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_options_are_registered_with_electrical_evidence():
    for name in ("AGAMEMNON_IO_PULLUP", "AGAMEMNON_IO_OPEN_DRAIN"):
        spec = OPTIONS[name]
        assert spec.kind == "csv" and spec.maturity == "experimental"
        assert spec.evidence == "qualification/fabric_io_electrical_evidence.jsonl"
        assert (ROOT / spec.evidence).exists()


def test_table_covers_the_measured_pads_only():
    data = rows()
    pullups = {r["pin"] for r in data if r["field"] == "CFG_PULL_UP"}
    assert len(pullups) == 22
    assert not (pullups & NO_EFFECT_PADS), "no-effect pad sites must stay out"
    assert {r["pin"] for r in data if r["field"] == "CFG_OPEN_DRAIN"} == {"PIN_26"}
    silicon = {(r["pin"], r["field"]) for r in data if r["witness"] == "silicon"}
    assert silicon == {("PIN_16", "CFG_PULL_UP"), ("PIN_26", "CFG_OPEN_DRAIN")}
    for row in data:
        byte = int(row["raw_byte"])
        assert 0 <= byte < preamble.PREAMBLE_LENGTH, "electrical bits are preamble-region"
        assert 0 <= int(row["bit"]) <= 7


def test_measured_anchors_match_the_silicon_witnesses():
    by_key = {(r["pin"], r["field"]): (int(r["raw_byte"]), int(r["bit"]))
              for r in rows()}
    assert by_key[("PIN_16", "CFG_PULL_UP")] == PIN16_PULLUP
    assert by_key[("PIN_26", "CFG_OPEN_DRAIN")] == PIN26_OPEN_DRAIN
    # The decoded SINGLE chain orders INPUT_EN, PULL_UP, SLR, OPEN_DRAIN, so a
    # pad's open-drain bit sits two bit positions past its pull-up anchor.
    pu_byte, pu_bit = by_key[("PIN_26", "CFG_PULL_UP")]
    od_byte, od_bit = by_key[("PIN_26", "CFG_OPEN_DRAIN")]
    assert (od_byte * 8 + od_bit) == (pu_byte * 8 + pu_bit) + 2


def test_requests_resolve_to_exactly_the_measured_bits():
    state = PhysicalIoState()
    FEATURE._prepare_electrical(state, CHIPDB, EngineOptions({
        "AGAMEMNON_IO_PULLUP": "PIN_16,PIN_25",
        "AGAMEMNON_IO_OPEN_DRAIN": "PIN_26",
    }))
    assert {(pin, fieldname) for pin, fieldname, _b, _m in state.electrical_used} == {
        ("PIN_16", "CFG_PULL_UP"), ("PIN_25", "CFG_PULL_UP"),
        ("PIN_26", "CFG_OPEN_DRAIN"),
    }
    bits = dict(((pin, fieldname), (byte, mask))
                for pin, fieldname, byte, mask in state.electrical_used)
    assert bits[("PIN_16", "CFG_PULL_UP")] == (90, 1 << 1)
    assert bits[("PIN_26", "CFG_OPEN_DRAIN")] == (10, 1 << 7)
    assert (90, 1 << 1) in FEATURE.writable_bits(state)


@pytest.mark.parametrize("pin", sorted(NO_EFFECT_PADS)[:4])
def test_unmeasured_pads_fail_closed(pin):
    state = PhysicalIoState()
    with pytest.raises(SystemExit):
        FEATURE._prepare_electrical(
            state, CHIPDB, EngineOptions({"AGAMEMNON_IO_PULLUP": pin})
        )


def test_no_request_emits_nothing():
    state = PhysicalIoState()
    FEATURE._prepare_electrical(state, CHIPDB, EngineOptions({}))
    assert state.electrical_used == []
    # And a None options mapping (non-bitgen callers) is inert.
    FEATURE._prepare_electrical(state, CHIPDB, None)
    assert state.electrical_used == []


def test_emission_sets_the_bit_over_the_regenerated_preamble():
    """The bit must survive preamble regeneration: it is applied after it."""
    state = PhysicalIoState()
    FEATURE._prepare_electrical(state, CHIPDB, EngineOptions({
        "AGAMEMNON_IO_PULLUP": "PIN_16",
    }))
    image = bytearray(agasc.RAW_LEN)
    image[:preamble.PREAMBLE_LENGTH] = preamble.IDLE_PROFILE

    class _Context:
        pass

    context = _Context()
    context.image = image
    context.state = state
    context.ownership = None
    assert FEATURE.emit_pad_electrical(context) == 1
    assert image[90] == preamble.IDLE_PROFILE[90] | 0x02
    assert image[90] != preamble.IDLE_PROFILE[90]
