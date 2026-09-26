"""A completed admissible mapping must not wait on an unbounded alternative."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon import cli
from agamemnon.engine import attempt_ladder as ladder


def attempt(log, outcome=ladder.NOT_ROUTED):
    return ladder.AttemptRecord(1, 0, '1', 0, outcome, log)


DEADLINE = attempt('AGaMEMnon place&route time limit exceeded (60 seconds); attempt is incomplete')
PLACEMENT = attempt('Unable to place cell')


def setup_wrapper(tmp_path, monkeypatch, timeout=None):
    monkeypatch.setattr(cli, '_native_srst_auto_enabled', lambda a: True)
    monkeypatch.setattr(cli, '_compare_control_sharing', lambda a, result, root: (result, {}))
    for key in cli._NATIVE_MAPPING_OPTION_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv('AGRV2K_SHARED_CONTROL_SRST_RECOVERY', raising=False)
    args = SimpleNamespace(input='top.v', sources=[], pcf=None, baseline=None,
                           output=str(tmp_path/'out.bin'), write_routed=str(tmp_path/'out.json'),
                           attempt_timeout=timeout)
    return args


def emitted(candidate, label, slices=50):
    path = Path(candidate.output)
    path.write_bytes(label.encode())
    Path(str(path)+'.comp').write_bytes((label+' compressed').encode())
    routed = Path(candidate.write_routed)
    routed.write_text('{}')
    for key in ['AGAMEMNON_POLICY_SIDECAR', 'AGAMEMNON_OWNERSHIP_TRACE']:
        if os.environ.get(key):
            Path(os.environ[key]).write_text(label+' '+key)
    return dict(output=str(path), routed_json=str(routed), slice_count=slices,
                occupied_tiles=4, routed_sha256=cli._sha256_file(routed), eligible_srst_cells=1)


@pytest.mark.parametrize('user_timeout,expected', [(None, 60.0), (7.0, 7.0), (120.0, 60.0)])
def test_alternative_deadline_preserves_completed_products_and_user_limits(
        tmp_path, monkeypatch, user_timeout, expected):
    args = setup_wrapper(tmp_path, monkeypatch, user_timeout)
    policy, ownership = tmp_path/'policy.json', tmp_path/'ownership.json'
    monkeypatch.setenv('AGAMEMNON_POLICY_SIDECAR', str(policy))
    monkeypatch.setenv('AGAMEMNON_OWNERSHIP_TRACE', str(ownership))
    seen = []
    def build(candidate):
        recovered = os.environ['AGRV2K_SHARED_CONTROL_SRST_RECOVERY'] == '1'
        seen.append(candidate)
        if recovered:
            assert candidate._native_srst_comparison_budget is None
            assert candidate.attempt_timeout == user_timeout
            return emitted(candidate, 'recovered')
        assert candidate.attempt_timeout == expected
        for _ in range(3):
            candidate._native_srst_comparison_budget.observe(DEADLINE)
        pytest.fail('optional mapping exceeded its route allowance')
    monkeypatch.setattr(cli, '_cmd_build_once', build)
    result = cli.cmd_build(args)
    assert len(seen) == 2 and result['mapping'] == 'recovered'
    assert args.attempt_timeout == user_timeout
    assert Path(args.output).read_bytes() == b'recovered'
    assert Path(args.output+'.comp').read_bytes() == b'recovered compressed'
    assert Path(args.write_routed).read_text() == '{}'
    assert policy.read_text() == 'recovered AGAMEMNON_POLICY_SIDECAR'
    assert ownership.read_text() == 'recovered AGAMEMNON_OWNERSHIP_TRACE'
    assert os.environ['AGAMEMNON_POLICY_SIDECAR'] == str(policy)
    assert os.environ['AGAMEMNON_OWNERSHIP_TRACE'] == str(ownership)
    assert 'AGRV2K_SHARED_CONTROL_SRST_RECOVERY' not in os.environ
    report = json.loads(Path(args.output+'.native-srst-selection.json').read_text())
    assert report['selected_image_sha256'] == cli._sha256_file(args.output)
    alternative = report['candidates'][1]
    assert alternative['outcome'] == 'optional_route_budget_expired'
    assert alternative['route_attempt_budget'] == dict(
        max_route_attempts=3, attempts_run=3, attempt_timeout_seconds=expected)


@pytest.mark.parametrize('first', ['exhausted', 'unsafe'])
def test_no_admissible_baseline_keeps_normal_alternative_search(tmp_path, monkeypatch, first):
    args = setup_wrapper(tmp_path, monkeypatch, 120.0)
    if first == 'unsafe':
        answers = iter([False, True, True])
        monkeypatch.setattr(cli, '_native_enable_qin_safe', lambda *args: next(answers))
    calls = []
    def build(candidate):
        recovered = os.environ['AGRV2K_SHARED_CONTROL_SRST_RECOVERY'] == '1'
        calls.append(candidate)
        assert candidate._native_srst_comparison_budget is None
        assert candidate.attempt_timeout == 120.0
        if recovered and first == 'exhausted':
            raise cli._NativeSRSTCandidateExhausted()
        return emitted(candidate, 'recovered' if recovered else 'legacy')
    monkeypatch.setattr(cli, '_cmd_build_once', build)
    assert cli.cmd_build(args)['mapping'] == 'legacy'
    assert len(calls) == 2


def test_completed_cheaper_alternative_still_wins(tmp_path, monkeypatch):
    args = setup_wrapper(tmp_path, monkeypatch)
    def build(candidate):
        recovered = os.environ['AGRV2K_SHARED_CONTROL_SRST_RECOVERY'] == '1'
        if not recovered:
            candidate._native_srst_comparison_budget.observe(attempt('Routing complete', ladder.SUCCESS))
        return emitted(candidate, 'recovered' if recovered else 'legacy', 50 if recovered else 40)
    monkeypatch.setattr(cli, '_cmd_build_once', build)
    assert cli.cmd_build(args)['mapping'] == 'legacy'
    assert Path(args.output).read_bytes() == b'legacy'


def test_recursive_fallbacks_share_the_mapping_budget():
    args = SimpleNamespace(_native_srst_comparison_budget=cli._NativeSRSTComparisonBudget(SimpleNamespace()))
    args._native_srst_comparison_budget.observe(PLACEMENT)
    retry = copy.copy(args)
    retry._native_srst_comparison_budget.observe(DEADLINE)
    nested = copy.copy(retry)
    with pytest.raises(cli._NativeSRSTComparisonExhausted) as error:
        nested._native_srst_comparison_budget.observe(PLACEMENT)
    assert error.value.report() == dict(outcome='optional_route_budget_expired', attempts_run=3,
                                      max_route_attempts=3, attempt_timeout_seconds=60.0)


@pytest.mark.parametrize('bad', [attempt('unclassified error'),
    attempt('Routing complete', ladder.TIMING_FAILED),
    attempt('unsafe route', ladder.ROUTED_UNSAFE),
    attempt('abort', ladder.ABORTED), attempt('hardware refusal', ladder.NONRETRYABLE)])
def test_budget_cannot_hide_an_unsafe_or_unknown_attempt(bad):
    budget = cli._NativeSRSTComparisonBudget(SimpleNamespace())
    budget.observe(bad)
    budget.observe(DEADLINE)
    with pytest.raises(SystemExit) as error:
        budget.observe(DEADLINE)
    assert error.value.code == 1


def test_alternative_safety_exit_is_not_replaced_by_baseline(tmp_path, monkeypatch):
    args = setup_wrapper(tmp_path, monkeypatch)
    def build(candidate):
        if os.environ['AGRV2K_SHARED_CONTROL_SRST_RECOVERY'] == '1':
            return emitted(candidate, 'recovered')
        raise SystemExit(1)
    monkeypatch.setattr(cli, '_cmd_build_once', build)
    with pytest.raises(SystemExit):
        cli.cmd_build(args)
    assert not Path(args.output).exists()
    assert 'AGRV2K_SHARED_CONTROL_SRST_RECOVERY' not in os.environ
