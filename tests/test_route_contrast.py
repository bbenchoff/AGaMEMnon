import csv
import json

from qualification.route_contrast import contrast, filter_devdb, routed_pips


def _route(path, *pips):
    fields = []
    for index, pip in enumerate(pips):
        fields.extend((f"W{index}", pip, "1"))
    path.write_text(json.dumps({"modules": {"top": {"netnames": {
        "n": {"attributes": {"ROUTING": ";".join(fields)}}
    }}}}), encoding="utf-8")


def test_contrast_never_selects_a_pip_seen_in_a_pass(tmp_path):
    live = tmp_path / "live.json"
    dead1 = tmp_path / "dead1.json"
    dead2 = tmp_path / "dead2.json"
    _route(live, "A.B", "C.D")
    _route(dead1, "A.B", "E.F")
    _route(dead2, "E.F", "G.H")
    assert routed_pips(live) == {"A.B", "C.D"}
    assert contrast([live], [dead1, dead2], 2) == [("E.F", 0, 2)]


def test_filter_devdb_removes_only_candidates(tmp_path):
    source = tmp_path / "dev_pips.csv"
    output = tmp_path / "filtered.csv"
    source.write_text("name,type,src,dst\nA.B,ROUTE,A,B\nE.F,ROUTE,E,F\n", encoding="utf-8")
    kept, removed = filter_devdb(source, output, [("E.F", 0, 2)])
    assert (kept, removed) == (1, 1)
    with output.open(newline="", encoding="utf-8") as f:
        assert list(csv.reader(f)) == [
            ["name", "type", "src", "dst"],
            ["A.B", "ROUTE", "A", "B"],
        ]
