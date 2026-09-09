"""Withdrawn selectors cannot reenter new emission through fallback tiers."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon.engine import retained_routing as rr, special_routes
from agamemnon.engine.registry import EngineOptions
from agamemnon.engine.features.routing import FEATURE as ROUTING_FEATURE
from agamemnon.engine.features.physical_io import PhysicalIoState

ROOT = Path(__file__).resolve().parents[1]


def checkpoint():
    path = ROOT / 'qualification/serv_rv32i_smoke_L48_routed.json'
    module = special_routes.physical_top_module(json.loads(path.read_text()))
    return path, module, EngineOptions(dict(rr.SERV_ENVIRONMENT))


def test_historical_checkpoint_binds_both_emission_epochs(tmp_path):
    path, module, options = checkpoint()
    assert rr.authenticate(rr.SERV_PIPS, {}, path, module, options) == (
        rr.SERV_PIPS, rr.SERV_IMAGE_SHA256)
    crlf = tmp_path / 'renamed.json'
    crlf.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    assert rr.authenticate(rr.SERV_PIPS, {}, crlf, module, options)[1] == rr.SERV_IMAGE_SHA256
    old = EngineOptions(dict(rr.SERV_ENVIRONMENT, AGAMEMNON_RETAINED_REPLAY='pre-owner-v1'))
    assert rr.authenticate(rr.SERV_PIPS, {}, path, module, old)[1] == rr.SERV_PRE_OWNER_SHA256


def test_no_exception_for_changed_checkpoint_module_or_environment(tmp_path):
    path, module, options = checkpoint()
    changed = tmp_path / 'changed.json'
    changed.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='exact retained checkpoint'):
        rr.authenticate(rr.SERV_PIPS, {}, changed, module, options)
    altered = dict(module, attributes=dict(module.get('attributes', {}), mutation=1))
    with pytest.raises(ValueError, match='exact retained checkpoint'):
        rr.authenticate(rr.SERV_PIPS, {}, path, altered, options)
    with pytest.raises(ValueError, match='environment mismatch'):
        rr.authenticate(rr.SERV_PIPS, {}, path, module,
                        EngineOptions(dict(rr.SERV_ENVIRONMENT, AGAMEMNON_SYSCLK='24')))


@pytest.mark.parametrize('pip', [
    'X18Y2_RMUX27.X18Y5_RMUX20',
    'X14Y11_RMUX07.X14Y12_RMUX46',
    'X14Y7_RMUX15.X14Y7_RMUX69',
])
def test_other_withdrawn_translations_refused_before_resolving(pip):
    with pytest.raises(ValueError, match='withdrawn selector translation'):
        rr.authenticate([pip], {}, None, None, EngineOptions({}))
    # Direct emission must refuse before touching any selector resolver. These
    # deliberately incomplete tables would fail if the guard came too late.
    with pytest.raises(SystemExit, match='withdrawn selector translation'):
        ROUTING_FEATURE.prepare(
            pips=[pip], cell={}, options=EngineOptions({}),
            tables=SimpleNamespace(clean_edge={}, admitted_edge={}, admission_binding=None),
            physical_io_state=PhysicalIoState(), exact_mcu_pips={}, mcu_cells={},
            mcu_exit_pairs={}, bram_feature=None, bram_state=None,
            slice_config={}, left_vendor_slices=set())


def test_exact_observation_remains_admitted_without_replay():
    pip = 'X13Y1_RMUX27.X13Y4_RMUX20'
    clean = {(13, 4, 'RMUX', 20, 'RMUX', 13, 1, 27): (2, 9)}
    assert rr.authenticate([pip], clean, None, None, EngineOptions({})) == (frozenset(), None)
