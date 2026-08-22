"""Unit tests for the G5 layer-1 router2 capability probe (agamemnon/engine/router2_probe.py).

Pure-Python: no real nextpnr binary is ever invoked. ``probe_router2``/``check_router2`` always
take an injected ``probe_fn`` (or, for ``check_router2``, one can be supplied to override the
bundled default), so the caching/identity/decision-policy logic -- the part of layer 1 this task
can actually validate without a build -- is fully exercised here. See
``agamemnon/engine/router2_probe.py``'s module docstring for why the bundled default fixture
(``run_example_fixture_probe``) is deliberately a sanity check, not a defect detector, and why it
is not exercised end-to-end by this test file (it needs a real nextpnr binary).
"""
import json
import os

import pytest

from agamemnon.engine import router2_probe as P


def _fake_argv(tmp_path, name="fake_nextpnr"):
    exe = tmp_path / name
    exe.write_bytes(b"not a real binary, just needs to exist for os.stat")
    return [str(exe)]


def _outcome_runner(verdict, detail="detail"):
    calls = []

    def _runner(argv, env):
        calls.append((list(argv), dict(env or {})))
        return P.ProbeRunOutcome(verdict, detail)

    _runner.calls = calls
    return _runner


# ---------------------------------------------------------------------------------------------
# binary_identity
# ---------------------------------------------------------------------------------------------

def test_binary_identity_is_stable_for_the_same_file(tmp_path):
    argv = _fake_argv(tmp_path)
    assert P.binary_identity(argv) == P.binary_identity(argv)


def test_binary_identity_changes_when_the_file_is_modified(tmp_path):
    argv = _fake_argv(tmp_path)
    before = P.binary_identity(argv)
    exe = tmp_path / "fake_nextpnr"
    exe.write_bytes(b"different content, different size")
    after = P.binary_identity(argv)
    assert before != after


def test_binary_identity_falls_back_to_argv_for_an_unresolvable_command():
    argv = ["definitely-not-a-real-command-xyz", "--uarch", "agrv2k"]
    key = P.binary_identity(argv, env={"PATH": ""})
    assert key.startswith("argv:")
    # deterministic for the same argv
    assert key == P.binary_identity(argv, env={"PATH": ""})
    # different argv -> different key
    assert key != P.binary_identity(argv + ["--extra"], env={"PATH": ""})


# ---------------------------------------------------------------------------------------------
# probe_router2: caching behaviour
# ---------------------------------------------------------------------------------------------

def test_probe_router2_runs_once_and_caches(tmp_path):
    argv = _fake_argv(tmp_path)
    cache_path = str(tmp_path / "cache.json")
    runner = _outcome_runner("ok", "routed fine")

    r1 = P.probe_router2(argv, {}, runner, cache_path=cache_path)
    assert r1.verdict == "ok" and r1.cached is False
    assert len(runner.calls) == 1

    r2 = P.probe_router2(argv, {}, runner, cache_path=cache_path)
    assert r2.verdict == "ok" and r2.cached is True
    assert len(runner.calls) == 1, "second call must reuse the cache, not re-run the probe"


def test_probe_router2_force_bypasses_the_cache_but_still_updates_it(tmp_path):
    argv = _fake_argv(tmp_path)
    cache_path = str(tmp_path / "cache.json")
    runner = _outcome_runner("ok")
    P.probe_router2(argv, {}, runner, cache_path=cache_path)
    assert len(runner.calls) == 1

    r = P.probe_router2(argv, {}, runner, cache_path=cache_path, force=True)
    assert len(runner.calls) == 2
    assert r.cached is False


def test_probe_router2_force_does_not_erase_other_binaries_cached_entries(tmp_path):
    argv_a = _fake_argv(tmp_path, "a")
    argv_b = _fake_argv(tmp_path, "b")
    cache_path = str(tmp_path / "cache.json")
    runner_ok = _outcome_runner("ok")
    runner_buggy = _outcome_runner("buggy", "known defect")

    P.probe_router2(argv_a, {}, runner_ok, cache_path=cache_path)
    P.probe_router2(argv_b, {}, runner_buggy, cache_path=cache_path)

    with open(cache_path, encoding="utf-8") as fh:
        before = json.load(fh)
    assert len(before) == 2

    # A forced re-probe of A must not wipe B's cached "buggy" verdict.
    P.probe_router2(argv_a, {}, runner_ok, cache_path=cache_path, force=True)
    r_b = P.probe_router2(argv_b, {}, runner_buggy, cache_path=cache_path)
    assert r_b.verdict == "buggy" and r_b.cached is True
    assert len(runner_buggy.calls) == 1, "B must have been served from cache, not re-run"


def test_probe_router2_cache_key_is_per_binary(tmp_path):
    argv_a = _fake_argv(tmp_path, "a")
    argv_b = _fake_argv(tmp_path, "b")
    cache_path = str(tmp_path / "cache.json")
    runner = _outcome_runner("ok")

    P.probe_router2(argv_a, {}, runner, cache_path=cache_path)
    P.probe_router2(argv_b, {}, runner, cache_path=cache_path)
    assert len(runner.calls) == 2, "different binaries must each be probed"


def test_probe_router2_bumping_probe_version_invalidates_the_cache(tmp_path, monkeypatch):
    argv = _fake_argv(tmp_path)
    cache_path = str(tmp_path / "cache.json")
    runner = _outcome_runner("ok")
    P.probe_router2(argv, {}, runner, cache_path=cache_path)
    assert len(runner.calls) == 1

    monkeypatch.setattr(P, "PROBE_VERSION", P.PROBE_VERSION + 1)
    P.probe_router2(argv, {}, runner, cache_path=cache_path)
    assert len(runner.calls) == 2, "a probe_version bump must force a fresh probe"


def test_probe_router2_survives_a_corrupt_cache_file(tmp_path):
    argv = _fake_argv(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{ not valid json", encoding="utf-8")
    runner = _outcome_runner("ok")
    r = P.probe_router2(argv, {}, runner, cache_path=str(cache_path))
    assert r.verdict == "ok"


def test_probe_router2_survives_a_probe_runner_that_raises(tmp_path):
    argv = _fake_argv(tmp_path)
    cache_path = str(tmp_path / "cache.json")

    def exploding_runner(argv, env):
        raise RuntimeError("nextpnr fell over")

    r = P.probe_router2(argv, {}, exploding_runner, cache_path=cache_path)
    assert r.verdict == "inconclusive"
    assert "nextpnr fell over" in r.detail


def test_probe_router2_rejects_an_unrecognized_verdict_as_inconclusive(tmp_path):
    argv = _fake_argv(tmp_path)
    cache_path = str(tmp_path / "cache.json")

    def weird_runner(argv, env):
        return P.ProbeRunOutcome("maybe", "shrug")

    r = P.probe_router2(argv, {}, weird_runner, cache_path=cache_path)
    assert r.verdict == "inconclusive"


def test_probe_router2_cache_write_failure_does_not_crash(tmp_path, monkeypatch):
    argv = _fake_argv(tmp_path)
    # A directory, not a file: any attempt to write here as a plain file must fail cleanly.
    bad_cache_path = str(tmp_path)
    runner = _outcome_runner("ok")
    r = P.probe_router2(argv, {}, runner, cache_path=bad_cache_path)
    assert r.verdict == "ok"  # the probe result itself is unaffected by a cache write failure


# ---------------------------------------------------------------------------------------------
# check_router2: the fail/warn/skip decision policy
# ---------------------------------------------------------------------------------------------

def test_check_router2_off_mode_skips_without_running_the_probe(tmp_path):
    argv = _fake_argv(tmp_path)
    runner = _outcome_runner("buggy")
    r = P.check_router2(argv, {}, probe_fn=runner, mode="off",
                         cache_path=str(tmp_path / "cache.json"))
    assert r.verdict == "skipped"
    assert len(runner.calls) == 0


def test_check_router2_off_mode_via_env(tmp_path):
    argv = _fake_argv(tmp_path)
    runner = _outcome_runner("buggy")
    env = {"AGAMEMNON_ROUTER2_PROBE_MODE": "off"}
    r = P.check_router2(argv, env, probe_fn=runner, cache_path=str(tmp_path / "cache.json"))
    assert r.verdict == "skipped"
    assert len(runner.calls) == 0


def test_check_router2_returns_ok_verdict_through_to_the_caller(tmp_path):
    argv = _fake_argv(tmp_path)
    runner = _outcome_runner("ok", "routed cleanly")
    r = P.check_router2(argv, {}, probe_fn=runner, cache_path=str(tmp_path / "cache.json"))
    assert r.verdict == "ok"


def test_check_router2_returns_buggy_verdict_through_to_the_caller(tmp_path):
    argv = _fake_argv(tmp_path)
    runner = _outcome_runner("buggy", "known defect signature")
    r = P.check_router2(argv, {}, probe_fn=runner, cache_path=str(tmp_path / "cache.json"))
    assert r.verdict == "buggy"
    assert "known defect signature" in r.detail


def test_check_router2_with_no_probe_fn_and_no_default_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "get_default_probe_fn", lambda: None)
    argv = _fake_argv(tmp_path)
    r = P.check_router2(argv, {}, cache_path=str(tmp_path / "cache.json"))
    assert r.verdict == "skipped"
    assert "no validated router2 defect fixture" in r.detail


def test_check_router2_uses_the_registered_default_probe_fn_when_none_supplied(tmp_path, monkeypatch):
    runner = _outcome_runner("ok", "used the default")
    monkeypatch.setattr(P, "get_default_probe_fn", lambda: runner)
    argv = _fake_argv(tmp_path)
    r = P.check_router2(argv, {}, cache_path=str(tmp_path / "cache.json"))
    assert r.verdict == "ok" and "used the default" in r.detail
    assert len(runner.calls) == 1


def test_check_router2_force_env_var_bypasses_the_cache(tmp_path):
    argv = _fake_argv(tmp_path)
    runner = _outcome_runner("ok")
    cache_path = str(tmp_path / "cache.json")
    P.check_router2(argv, {}, probe_fn=runner, cache_path=cache_path)
    assert len(runner.calls) == 1
    P.check_router2(argv, {"AGAMEMNON_ROUTER2_PROBE_FORCE": "1"}, probe_fn=runner, cache_path=cache_path)
    assert len(runner.calls) == 2


def test_check_router2_unknown_mode_falls_back_to_enforce(tmp_path):
    argv = _fake_argv(tmp_path)
    runner = _outcome_runner("buggy")
    r = P.check_router2(argv, {}, probe_fn=runner, mode="not-a-real-mode",
                         cache_path=str(tmp_path / "cache.json"))
    # "enforce" is the fallback; check_router2 itself does not exit/raise -- it just reports the
    # verdict for the caller (agamemnon/cli.py) to act on, so this only proves the mode resolved
    # to something in the known set and the probe still ran.
    assert r.verdict == "buggy"


# ---------------------------------------------------------------------------------------------
# the bundled example-fixture JSON is well-formed and self-consistent
# ---------------------------------------------------------------------------------------------

def test_example_fixture_json_is_well_formed_and_wires_one_net_between_two_far_bels():
    doc = json.loads(P._example_fixture_json())
    module = doc["modules"]["top"]
    assert module["attributes"]["top"] == 1
    cells = module["cells"]
    assert set(cells) == {"u_src", "u_dst"}
    for cell in cells.values():
        assert cell["type"] == "LUT4"
        assert set(cell["port_directions"]) == {"I[0]", "I[1]", "I[2]", "I[3]", "F"}
    # exactly one shared net bit between the two cells
    src_bits = set(cells["u_src"]["connections"]["F"])
    dst_bits = set(cells["u_dst"]["connections"]["I[0]"])
    assert src_bits and src_bits == dst_bits
    assert cells["u_src"]["attributes"]["NEXTPNR_BEL"] != cells["u_dst"]["attributes"]["NEXTPNR_BEL"]
    net_bits = set(module["netnames"]["probe_net"]["bits"])
    assert net_bits == src_bits
