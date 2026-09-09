"""Replay identity must survive checkout EOLs and reject altered inputs/options."""
import hashlib
import json
from pathlib import Path
import pytest
from agamemnon.engine import retained_replay as replay, special_routes
from agamemnon.engine.features.clock_validate import validate_routed_clock
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


@pytest.mark.parametrize("wrap", [dict, EngineOptions])
def test_clock_replay_selection_accepts_mapping_and_engine_options(wrap):
    assert replay._selected_profile(None) is None
    assert replay._selected_profile(wrap({})) is None
    assert replay._selected_profile(wrap({replay.OPTION: replay.PROFILE})) == replay.PROFILE
    profile = "mcu-ahb-bank16-read-word0"
    assert replay._selected_profile(wrap({replay.QUALIFIED_OPTION: profile})) == profile
    with pytest.raises(ValueError, match="unknown qualified"):
        replay._selected_profile(wrap({replay.QUALIFIED_OPTION: "unknown"}))
    with pytest.raises(ValueError, match="mutually exclusive"):
        replay._selected_profile(wrap({replay.OPTION: replay.PROFILE,
                                       replay.QUALIFIED_OPTION: profile}))


@pytest.mark.parametrize("profile,routed", [
    ("mcu-ahb-bank16-read-word0",
     "qualification/mcu_ahb_register_bank16_read_word0_gated_routed.json"),
    ("mcu-ahb-bank16-public-scratch4",
     "qualification/mcu_ahb_register_bank16_public_scratch4_routed.json"),
])
def test_qualified_profile_replay_binds_only_its_exact_checkpoint(profile, routed):
    source = ROOT / routed
    module = special_routes.physical_top_module(json.loads(source.read_text()))
    options = EngineOptions({
        "AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10",
        replay.QUALIFIED_OPTION: profile,
    })
    assert replay.authenticate(options, source, module, DATA) == \
        replay.QUALIFIED_PROFILES[profile]["bitstream_sha256"]
    validation = validate_routed_clock(
        module, DATA, options,
        routed_sha256=replay.QUALIFIED_PROFILES[profile]["routed_sha256"],
    )
    assert validation.quarantined_bitstream_sha256 == \
        replay.QUALIFIED_PROFILES[profile]["bitstream_sha256"]
    wrong = next(name for name in replay.QUALIFIED_PROFILES if name != profile)
    with pytest.raises(ValueError, match="does not bind this checkpoint/image pair"):
        replay.authenticate(EngineOptions({
            "AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10",
            replay.QUALIFIED_OPTION: wrong,
        }), source, module, DATA)
    altered = dict(module, attributes=dict(module.get("attributes", {}), altered=1))
    with pytest.raises(Exception, match="exact authenticated checkpoint"):
        validate_routed_clock(
            altered, DATA, options,
            routed_sha256=replay.QUALIFIED_PROFILES[profile]["routed_sha256"],
        )


def test_qualified_replay_rejects_unknown_and_legacy_mode_combination():
    with pytest.raises(ValueError, match="unknown qualified"):
        replay._selected_profile(EngineOptions({replay.QUALIFIED_OPTION: "arbitrary"}))
    with pytest.raises(ValueError, match="mutually exclusive"):
        replay._selected_profile(EngineOptions({
            replay.OPTION: replay.PROFILE,
            replay.QUALIFIED_OPTION: "mcu-ahb-bank16-read-word0",
        }))
    assert replay.enabled(EngineOptions({replay.QUALIFIED_OPTION:
                                         "mcu-ahb-bank16-read-word0"})) is True

def test_registry_tamper(tmp_path):
    (tmp_path/"retained_pre_owner_v1.json").write_bytes((DATA/"retained_pre_owner_v1.json").read_bytes()+b" ")
    with pytest.raises(ValueError,match="digest mismatch"):
        replay.authenticate(EngineOptions({"AGAMEMNON_RETAINED_REPLAY":"pre-owner-v1"}),None,None,tmp_path)
