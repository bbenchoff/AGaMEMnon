import struct

import pytest

from agamemnon.engine import chipdb_schema


def test_agdb_round_trip_preserves_tuple_and_frozenset():
    mapping = {
        (1, "RMUX", frozenset({(2, "OMUX"), (3, "RMUX")})): frozenset({1, 7}),
        (2, "IMUX", frozenset()): (4, 9),
    }
    encoded = chipdb_schema.dumps({"routes": mapping}, metadata={"kind": "test"})
    decoded, metadata = chipdb_schema.loads(encoded, expected=("routes",))
    assert decoded == {"routes": mapping}
    assert metadata == {"kind": "test"}


def test_agdb_rejects_magic_schema_and_length_corruption():
    encoded = chipdb_schema.dumps({"data": {(1,): (2,)}})
    with pytest.raises(chipdb_schema.ChipDBError, match="not an AGDB"):
        chipdb_schema.loads(b"pickle is not data")
    wrong_schema = encoded[:5] + struct.pack(">H", 99) + encoded[7:]
    with pytest.raises(chipdb_schema.ChipDBError, match="unsupported AGDB schema"):
        chipdb_schema.loads(wrong_schema)
    wrong_length = encoded[:7] + struct.pack(">I", 1) + encoded[11:]
    with pytest.raises(chipdb_schema.ChipDBError, match="length mismatch"):
        chipdb_schema.loads(wrong_length)


def test_shipped_runtime_databases_have_expected_schema(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
    exact, _ = chipdb_schema.load(root / "sel_edge_pairs.agdb", expected=("clean_edge",))
    train, _ = chipdb_schema.load(root / "train_lut.agdb", expected=("train_lut",))
    tables, _ = chipdb_schema.load(
        root / "sel_tables.agdb", expected=("geom_rmux", "absolute", "group_context")
    )
    assert len(exact["clean_edge"]) == 659759
    assert len(train["train_lut"]) == 14237
    assert tuple(len(tables[name]) for name in ("geom_rmux", "absolute", "group_context")) == (
        330, 153080, 532558
    )
