import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_x9_haddr_corridor_and_fields_are_complete():
    paths = rows("bram_x9_haddr_paths.csv")
    fields = rows("bram_x9_haddr_pip_cfg.csv")
    assert len(paths) == 53
    assert len(fields) == 53
    assert {int(row["logical_bit"]) for row in paths} == set(range(2, 12))
    assert paths[0]["src_wire"] == "X13Y12_BufMUX12"
    assert paths[-1]["dst_wire"] == "X13Y4_IMUX00"
    assert {(row["src_wire"], row["dst_wire"]) for row in paths} == {
        (row["src_wire"], row["dst_wire"]) for row in fields
    }
    assert all(
        len(row["set_selectors"].split(";")) == 2
        for row in fields
        if row["cell_table"] == "fabric"
    )
    assert {
        (row["cfg_group"], row["clear_selectors"], row["set_selectors"])
        for row in fields
        if row["cell_table"] == "mcu"
    } == {("InputMUX1", "0", ""), ("InputMUX0", "0", "0")}


def test_x9_haddr_tables_are_consumed_by_arch_and_bitgen():
    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(encoding="utf-8")
    assert '"bram_x9_haddr_paths.csv"' in arch
    assert '"bram_x9_haddr_pip_cfg.csv"' in bitgen
    assert 'OPTIONS.enabled("AGAMEMNON_X9_FULL_ADDRESS")' in arch
    assert "any(_width == 8" in bitgen
    assert 'OPTIONS.enabled("AGAMEMNON_BRAM_HSE_INPUT")' in bitgen
    assert "if _clocked or _bram_hse_input:" in bitgen
    assert '"x9" if _bram_x9_hse_input else "forced"' in bitgen


def test_x9_haddr_table_is_replayed_atomically_by_uarch_packer():
    source = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8"
    )
    assert '"/bram_x9_haddr_paths.csv"' in source
    assert "pre-routed AddressA[%d] over %d exact x9 pip(s)" in source
    assert "pre-routed split AddressA[%d] prefix over %d exact x9 pip(s)" in source
    assert "checkPipAvailForNet(pip, net)" in source
    assert 'auto requested_bel = drv->attrs.find(ctx->id("BEL"));' in source
    assert 'items[ii].drv->attrs.erase(ctx->id("BEL"));' in source
    assert "for (int bit = 3; bit <= 12; ++bit)" in source


def test_memory_libmap_address_alignment_is_preserved_for_narrow_modes():
    mapping = (ROOT / "agamemnon" / "synth" / "ag32_brams_map.v").read_text(
        encoding="utf-8"
    )
    # memory_libmap aligns a x9 word index in PORT_*_ADDR[12:3].  Re-slicing
    # [9:0] and appending 3'b111 shifts it a second time and connects logical
    # address bit zero to physical Address[6] instead of Address[3].
    assert "{PORT_A_ADDR[12:3], 3'b111}" in mapping
    assert "{PORT_B_ADDR[12:3], 3'b111}" in mapping
    assert "{PORT_A_ADDR[9:0], 3'b111}" not in mapping


def test_x9_negative_and_haddr_isolation_evidence_are_retained():
    ledger = ROOT / "qualification" / "bram_evidence.jsonl"
    records = {
        row["trial_id"]: row
        for row in (json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines())
        if "trial_id" in row
    }
    x9 = records["2026-08-02-l48-open-porta-x9-recovered-address"]
    assert x9["result"] == "static_not_qualified"
    assert x9["values"] == ["0xfffffff8"]
    assert x9["selectors"]["selector_mismatches"] == 0

    capture = records["2026-08-02-l48-mcu-haddr-capture-2-4"]
    assert capture["result"] == "pass_dynamic_boundary_isolation"
    assert capture["distinct_per_run"] == [8]
    assert capture["counts_per_value"] == [32] * 8

    for source, record in (
        (ROOT / "qualification" / "bram_x9_ahb_address.v", x9),
        (ROOT / "qualification" / "mcu_haddr_capture.v", capture),
    ):
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record["source_sha256"]


def test_x9_data6_full_width_projection_and_silicon_record_are_retained():
    source = (ROOT / "qualification" / "bram_x9_data6_direct.v").read_text(
        encoding="utf-8"
    )
    assert "mem[i] = {i[2:0], i[8:3]};" in source
    assert "assign h0 = q[6];" in source

    records = {
        row["trial_id"]: row
        for row in (
            json.loads(line)
            for line in (ROOT / "qualification" / "bram_evidence.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if "trial_id" in row
    }
    data6 = records["2026-08-04-l48-x9-data6-direct"]
    assert data6["verdict"] == "pass"
    assert data6["source_wire"] == "X13Y4_BufMUX14"
    assert data6["observed_wire"] == "X0Y5_SinkMUXPseudo02"
    assert len(data6["path_pips"]) == 9
    assert data6["bitstream_sha256"] == (
        "d4c01d1085777d931618947081841c9a7bd22d63574dc5df84e635f6afe2f8c5"
    )


def test_x9_data7_full_width_projection_and_silicon_record_are_retained():
    source = (ROOT / "qualification" / "bram_x9_data7_direct.v").read_text(
        encoding="utf-8"
    )
    assert "mem[i] = {i[2:0], i[8:3]};" in source
    assert "assign h0 = q[7];" in source

    records = {
        row["trial_id"]: row
        for row in (
            json.loads(line)
            for line in (ROOT / "qualification" / "bram_evidence.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if "trial_id" in row
    }
    data7 = records["2026-08-04-l48-x9-data7-direct"]
    assert data7["verdict"] == "pass"
    assert data7["source_wire"] == "X13Y4_BufMUX15"
    assert data7["observed_wire"] == "X0Y5_SinkMUXPseudo02"
    assert len(data7["path_pips"]) == 8
    assert data7["bitstream_sha256"] == (
        "ecdd2ba5c849bda233b8e4d15b57ab6de625c42db441e3746ad38eaa1e2848b4"
    )


def test_x9_data8_full_width_projection_and_silicon_record_are_retained():
    source = (ROOT / "qualification" / "bram_x9_data8_direct.v").read_text(
        encoding="utf-8"
    )
    assert "mem[i] = {i[2:0], i[8:3]};" in source
    assert "assign h0 = q[8];" in source

    records = {
        row["trial_id"]: row
        for row in (
            json.loads(line)
            for line in (ROOT / "qualification" / "bram_evidence.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if "trial_id" in row
    }
    data8 = records["2026-08-04-l48-x9-data8-direct"]
    assert data8["verdict"] == "pass"
    assert data8["source_wire"] == "X13Y4_BufMUX07"
    assert data8["observed_wire"] == "X0Y5_SinkMUXPseudo02"
    assert len(data8["path_pips"]) == 5
    assert data8["bitstream_sha256"] == (
        "415d4392ae9c035235f5b62a2b1ff33883255d61d9aaf10d17b6d9ae131f567b"
    )
