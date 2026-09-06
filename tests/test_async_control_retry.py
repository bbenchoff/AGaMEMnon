"""A missing control implementation is independent of placement attempts."""
from agamemnon.cli import _nonretryable_uarch_failure


def test_unsupported_reset_stops_the_attempt_ladder():
    assert _nonretryable_uarch_failure(
        "ERROR: agrv2k: pre-route DRC rejects shared control on 'state' at X14Y8_SLICE0: "
        "unsupported physical shared control ASYNC_CLEAR_POS_ZERO (positive polarity, clear value 0): "
        "route-bound configuration and HIL qualification remain incomplete")


def test_tile_capacity_failure_can_retry_another_placement():
    assert not _nonretryable_uarch_failure(
        "async tile needs 3 controls, including inactive registers; capacity is 2")
