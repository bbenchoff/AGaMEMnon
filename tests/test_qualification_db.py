import json
from argparse import Namespace

from agamemnon.engine.qualification_db import (
    fold_events,
    record,
    routed_nets,
    select_net,
    silicon_csv_pips,
    unique_path,
)


def _routed(tmp_path):
    path = tmp_path / "routed.json"
    route = (
        "X1Y1_SINKA;X1Y1_ROOT.X1Y1_SINKA;1;"
        "X1Y1_ROOT;;1;"
        "X2Y1_MID;X1Y1_ROOT.X2Y1_MID;1;"
        "X3Y1_OBS;X2Y1_MID.X3Y1_OBS;1"
    )
    path.write_text(json.dumps({"modules": {"top": {"netnames": {
        "probe": {"attributes": {"ROUTING": route}}
    }}}}), encoding="utf-8")
    return path


def test_selects_only_observed_branch(tmp_path):
    nets = routed_nets(_routed(tmp_path))
    pips = select_net(nets, "probe")
    path, source, sink = unique_path(pips, sink="X3Y1_OBS")
    assert source == "X1Y1_ROOT"
    assert sink == "X3Y1_OBS"
    assert path == ["X1Y1_ROOT.X2Y1_MID", "X2Y1_MID.X3Y1_OBS"]
    assert "X1Y1_ROOT.X1Y1_SINKA" not in path


def test_ambiguous_branch_requires_observed_wire(tmp_path):
    nets = routed_nets(_routed(tmp_path))
    pips = select_net(nets, "top/probe")
    try:
        unique_path(pips)
    except ValueError as exc:
        assert "leaves" in str(exc)
    else:
        raise AssertionError("branching route was accepted without an observed sink")


def test_fold_pass_fail_and_conflict():
    events = [
        {"trial_id": "pass-a", "verdict": "pass", "path_isolated": True,
         "path_pips": ["X1Y1_A.X1Y1_B", "X1Y1_B.X1Y1_C"]},
        {"trial_id": "fail-d", "verdict": "fail", "path_isolated": True,
         "dead_candidate": "X1Y1_C.X1Y1_D"},
        {"trial_id": "pass-conflict", "verdict": "pass", "path_isolated": True,
         "path_pips": ["X1Y1_C.X1Y1_D"]},
    ]
    state = fold_events(events)
    assert state["X1Y1_A.X1Y1_B"]["status"] == "live"
    assert state["X1Y1_C.X1Y1_D"]["status"] == "conflict"


def test_loads_seed_conduction_csv(tmp_path):
    path = tmp_path / "live.csv"
    path.write_text(
        "src_res,src_x,src_y,dst_res,dst_x,dst_y,source\n"
        "OMUX02,14,4,RMUX06,14,4,silicon\n",
        encoding="utf-8",
    )
    assert silicon_csv_pips([path]) == {"X14Y4_OMUX02.X14Y4_RMUX06"}


def test_record_rejects_duplicate_trial_id(tmp_path):
    routed = _routed(tmp_path)
    database = tmp_path / "evidence.jsonl"
    args = Namespace(
        routed=str(routed), net="probe", source_wire=None,
        observed_wire="X3Y1_OBS", database=str(database), seed_live=[],
        verdict="pass", trial_id="trial-1", campaign="test",
        probe="digital_path", bitstream=None, expected="toggle",
        observed="toggle", notes="", min_dead_observations=2,
    )
    record(args)
    event = json.loads(database.read_text(encoding="utf-8").splitlines()[0])
    assert event["routed_json"] == "routed.json"
    try:
        record(args)
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate qualification trial was appended")


def test_record_uses_portable_labels_for_absolute_artifacts(tmp_path):
    routed = _routed(tmp_path)
    bitstream = tmp_path / "fabric.bin"
    bitstream.write_bytes(b"offline fixture")
    database = tmp_path / "evidence.jsonl"
    args = Namespace(
        routed=str(routed.resolve()), net="probe", source_wire=None,
        observed_wire="X3Y1_OBS", database=str(database), seed_live=[],
        verdict="pass", trial_id="portable-1", campaign="test",
        probe="digital_path", bitstream=str(bitstream.resolve()), expected="toggle",
        observed="toggle", notes="", min_dead_observations=2,
    )
    record(args)
    event = json.loads(database.read_text(encoding="utf-8").splitlines()[0])
    assert event["routed_json"] == "routed.json"
    assert event["bitstream"] == "fabric.bin"
    assert str(tmp_path) not in database.read_text(encoding="utf-8")


def test_dead_edge_requires_repeated_isolated_failure(tmp_path):
    routed = _routed(tmp_path)
    database = tmp_path / "evidence.jsonl"
    seed = tmp_path / "seed.csv"
    seed.write_text(
        "src_res,src_x,src_y,dst_res,dst_x,dst_y,source\n"
        "ROOT,1,1,MID,2,1,silicon\n",
        encoding="utf-8",
    )
    base = dict(
        routed=str(routed), net="probe", source_wire=None,
        observed_wire="X3Y1_OBS", database=str(database), seed_live=[str(seed)],
        verdict="fail", campaign="test", probe="digital_path", bitstream=None,
        expected="toggle", observed="stuck", notes="", min_dead_observations=2,
    )
    first = Namespace(**base, trial_id="fail-1")
    record(first)
    events = [json.loads(line) for line in database.read_text().splitlines()]
    assert events[0]["resolution"] == "dead_suspect"
    assert events[0]["dead_candidate"] is None
    assert fold_events(events) == {}

    second = Namespace(**base, trial_id="fail-2")
    record(second)
    events = [json.loads(line) for line in database.read_text().splitlines()]
    assert events[1]["resolution"] == "dead_edge"
    assert events[1]["failure_observation"] == 2
    state = fold_events(events)
    assert state[events[1]["dead_candidate"]]["status"] == "dead"
