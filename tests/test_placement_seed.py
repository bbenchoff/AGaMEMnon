"""Explicit seeds must survive retries and project configuration without silent fallback."""
from types import SimpleNamespace

import pytest

from agamemnon import cli, project


@pytest.mark.parametrize('seed', [0, 7, 0xffffffff])
@pytest.mark.parametrize('generic', [False, True])
def test_explicit_seed_overrides_each_placement_family(generic, seed):
    assert cli._validate_placement_seed(seed) == seed
    assert cli._uarch_placement_seeds(generic, ['99'], seed) == [str(seed)]


def test_default_seed_sweeps_and_legacy_constructive_override_are_preserved():
    assert cli._uarch_placement_seeds(True, ['99']) == ['1','2','3','4']
    assert cli._uarch_placement_seeds(False, ['4','2','7']) == ['4','2','7']
    assert cli._uarch_placement_seeds(False, ['99']) == ['99']


@pytest.mark.parametrize('seed', [-1, 2**32, True, 1.5, '7'])
def test_invalid_seed_stops_before_loading_sources(seed, monkeypatch, capsys):
    monkeypatch.setattr(project.Project, 'load', lambda *a: pytest.fail('must reject before project load'))
    with pytest.raises(SystemExit) as error:
        cli.cmd_build(SimpleNamespace(seed=seed))
    assert error.value.code == 2
    assert '--seed must be an integer between' in capsys.readouterr().out


@pytest.mark.parametrize('seed', ['-1', str(2**32)])
def test_cli_rejects_invalid_seed_before_native_candidate_setup(seed, monkeypatch, capsys):
    monkeypatch.setattr(cli.tempfile, 'mkdtemp', lambda *a, **k: pytest.fail('must reject before candidate setup'))
    with pytest.raises(SystemExit) as error:
        cli.main(['build','nonexistent.v','--uarch','--seed',seed])
    assert error.value.code == 2
    assert '--seed must be an integer between' in capsys.readouterr().out


@pytest.mark.parametrize('options,message', [
    ([], '--seed requires --uarch'),
    (['--uarch','--qualified-checkpoint','unused-profile'], 'fixed qualified profile'),
    (['--uarch','--qualified-bram-write','unused-profile'], 'fixed qualified profile'),
])
def test_inapplicable_seed_is_rejected_before_tools(options, message, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_run_child', lambda *a, **k: pytest.fail('must not run tools'))
    with pytest.raises(SystemExit) as error:
        cli.main(['build','nonexistent.v','--seed','0', *options])
    assert error.value.code == 2
    assert message in capsys.readouterr().out


@pytest.mark.parametrize('cli_seed,expected', [(None, 7), (0, 0), (19, 19)])
def test_project_seed_defaults_and_cli_precedence(tmp_path, monkeypatch, cli_seed, expected):
    monkeypatch.setenv('AGAMEMNON_DEVICE', 'restore-after-test')
    loaded = project.Project(tmp_path, {'fabric': {'sources':['top.v'], 'seed':7}})
    args = SimpleNamespace(seed=cli_seed)
    assert project.apply_fabric_config(args, loaded)
    assert args.seed == expected


@pytest.mark.parametrize('fabric,external,message', [
    ({'seed':True, 'sources':['top.v']}, {}, '--seed must be an integer'),
    ({'seed':7}, {}, 'source-based native FPGA project'),
    ({'seed':7, 'qualified_profile':'fixed'}, {}, 'source-based native FPGA project'),
    ({'seed':7, 'sources':['top.v'], 'uarch':False}, {}, 'source-based native FPGA project'),
    ({'seed':7, 'sources':['top.v']}, {'build':['unused']}, 'source-based native FPGA project'),
])
def test_project_seed_cannot_be_ignored_by_other_build_paths(
        tmp_path, monkeypatch, capsys, fabric, external, message):
    loaded = project.Project(tmp_path, {'fabric':fabric, 'external':external})
    monkeypatch.setattr(project.Project, 'load', lambda *a: loaded)
    for name in ('build_external', 'build_qualified_fabric', 'build_mcu'):
        monkeypatch.setattr(project, name, lambda *a: pytest.fail('must reject before project build'))
    with pytest.raises(SystemExit) as error:
        cli.main(['build'])
    assert error.value.code == 2
    assert message in capsys.readouterr().out
