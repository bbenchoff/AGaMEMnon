import csv
import pickle

from qualification.clean_sel_blocks import main, recover


FIELDS = [
    "build",
    "dst_x",
    "dst_y",
    "dst_fam",
    "dst_idx",
    "src_fam",
    "src_x",
    "src_y",
    "src_idx",
    "dst_group_offset",
    "sel",
]


def _edge(build, dst_idx, offset, sels):
    return [
        {
            "build": build,
            "dst_x": "12",
            "dst_y": "3",
            "dst_fam": "RMUX",
            "dst_idx": str(dst_idx),
            "src_fam": "OMUX",
            "src_x": "12",
            "src_y": "3",
            "src_idx": str(20 + dst_idx),
            "dst_group_offset": str(offset),
            "sel": str(sel),
        }
        for sel in sels
    ]


def test_node_blocks_are_independent_and_conflicts_fail_closed(tmp_path):
    dataset = tmp_path / "selectors.csv"
    rows = []
    rows += _edge("build-a", 0, 0, [1, 7, 12, 18])
    rows += _edge("build-a", 1, 1, [1, 7, 12, 18])
    rows += _edge("build-b", 0, 0, [2, 8])
    with dataset.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    table, stats = recover(dataset)
    edge0 = (12, 3, "RMUX", 0, "OMUX", 12, 3, 20)
    edge1 = (12, 3, "RMUX", 1, "OMUX", 12, 3, 21)
    assert table[edge0]["variants"] == 2
    assert table[edge1]["pair"] == (2, 8)
    assert stats["consistent_keys"] == 1

    output = tmp_path / "runtime.pkl"
    main([str(dataset), str(output), "--runtime"])
    with output.open("rb") as stream:
        runtime = pickle.load(stream)
    assert edge0 not in runtime["table"]
    assert runtime["table"][edge1] == (2, 8)
