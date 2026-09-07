"""Replay identity must survive checkout EOLs and reject altered inputs/options."""
import hashlib
import json
from pathlib import Path
import pytest
from agamemnon.engine import retained_replay as replay, special_routes
from agamemnon.engine.registry import EngineOptions

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"agamemnon/chipdb"
MANIFEST=ROOT/"qualification/pack_regression_pre_owner_v1.json"
ROWS=json.loads(MANIFEST.read_text())["artifacts"]

def test_original_manifest_identity():
    assert hashlib.sha256(MANIFEST.read_bytes().replace(b"\r\n",b"\n")).hexdigest()=="88dc725fe2feb5cc64b824e028333c0a98183578be9e9d432df42dca2497c243"

@pytest.mark.parametrize("row",ROWS,ids=lambda r:Path(r["routed"]).stem)
def test_exact_original_checkpoint(row,tmp_path):
    source=ROOT/row["routed"]
    module=special_routes.physical_top_module(json.loads(source.read_text()))
    options=EngineOptions(dict(row["environment"],AGAMEMNON_RETAINED_REPLAY="pre-owner-v1"))
    assert replay.authenticate(options,source,module,DATA)==row["bitstream_sha256"]
    crlf=tmp_path/"checkout.json";crlf.write_bytes(source.read_bytes().replace(b"\r\n",b"\n").replace(b"\n",b"\r\n"))
    assert replay.authenticate(options,crlf,module,DATA)==row["bitstream_sha256"]

def test_reject_modified_checkpoint_and_options(tmp_path):
    row=ROWS[0];source=ROOT/row["routed"]
    module=special_routes.physical_top_module(json.loads(source.read_text()))
    env=dict(row["environment"],AGAMEMNON_RETAINED_REPLAY="pre-owner-v1")
    changed=tmp_path/"edited.json";changed.write_bytes(source.read_bytes()+b" ")
    with pytest.raises(ValueError,match="exact authenticated"):
        replay.authenticate(EngineOptions(env),changed,module,DATA)
    with pytest.raises(ValueError,match="environment mismatch"):
        replay.authenticate(EngineOptions(dict(env,AGAMEMNON_HSE="7")),source,module,DATA)
    altered=dict(module,attributes=dict(module.get("attributes",{}),unexpected=1))
    with pytest.raises(ValueError,match="exact authenticated"):
        replay.authenticate(EngineOptions(env),source,altered,DATA)

def test_default_and_unknown_version():
    assert replay.authenticate(EngineOptions({}),None,None,None) is None
    with pytest.raises(ValueError,match="unknown retained"):
        replay.enabled(EngineOptions({"AGAMEMNON_RETAINED_REPLAY":"anything"}))

def test_registry_tamper(tmp_path):
    (tmp_path/"retained_pre_owner_v1.json").write_bytes((DATA/"retained_pre_owner_v1.json").read_bytes()+b" ")
    with pytest.raises(ValueError,match="digest mismatch"):
        replay.authenticate(EngineOptions({"AGAMEMNON_RETAINED_REPLAY":"pre-owner-v1"}),None,None,tmp_path)
