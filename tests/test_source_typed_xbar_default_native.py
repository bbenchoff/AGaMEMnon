"""Native behavioral checks for the v0.4.0 source-typed default."""

from test_native_endpoint_legality import _consumer, _input_design, _run


def test_unset_source_typed_mode_accepts_fixed_reachable_odd_slice(tmp_path):
    result, log, output = _run(
        tmp_path, "odd_default", _input_design(consumer_bel="X19Y12_SLICE3"),
        "--no-route", "--placer", "heap",
        env_overrides={"AGRV2K_SOURCE_TYPED_XBAR": None},
    )
    assert result.returncode == 0, log
    assert _consumer(output)["attributes"]["NEXTPNR_BEL"] == "X19Y12_SLICE3"


def test_explicit_zero_source_typed_mode_retains_legacy_odd_rejection(tmp_path):
    result, log, _ = _run(
        tmp_path, "odd_legacy", _input_design(consumer_bel="X19Y12_SLICE3"),
        "--no-route", "--placer", "heap",
        env_overrides={"AGRV2K_SOURCE_TYPED_XBAR": "0"},
    )
    assert result.returncode != 0
    assert "ordinary cell 'consumer' at X19Y12_SLICE3 uses an unqualified odd slice" in log


def test_malformed_source_typed_mode_value_fails_closed(tmp_path):
    result, log, _ = _run(
        tmp_path, "odd_malformed", _input_design(consumer_bel="X19Y12_SLICE3"),
        "--no-route", "--placer", "heap",
        env_overrides={"AGRV2K_SOURCE_TYPED_XBAR": "yes"},
    )
    assert result.returncode != 0
    assert "AGRV2K_SOURCE_TYPED_XBAR must be exactly 0 or 1" in log
