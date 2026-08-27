from pathlib import Path

import pytest

from agamemnon import hil_campaign as H


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "qualification" / "fabric_ahb_read_observer_trace_r4.c"


def _pack_trace(samples):
    assert len(samples) == 64
    words = []
    for offset in range(0, 64, 8):
        word = 0
        for lane, sample in enumerate(samples[offset:offset + 8]):
            assert 0 <= sample <= 0xF
            word |= sample << (4 * lane)
        words.append(word)
    return words


def _active_words(phase0, phase1, phase2, marker0=0, marker1=1,
                  tag=0x41484252):
    return (_pack_trace(phase0) + _pack_trace(phase1) +
            _pack_trace(phase2) + [marker0, marker1, tag])


def _exact_rule(word, value):
    return {"word": word, "mask": "0xffffffff",
            "equals": "0x%08x" % value}


def _active_contract():
    rules = []
    for word in range(4, 8):
        rules.append(_exact_rule(word, 0x99999999))
    for word in range(12, 16):
        rules.append(_exact_rule(word, 0x88888888))
    for word in range(20, 24):
        rules.append(_exact_rule(word, 0x99999999))
    rules += [_exact_rule(24, 0), _exact_rule(25, 1),
              _exact_rule(26, 0x41484252)]
    all_zero = [_exact_rule(word, 0) for word in range(24)]
    all_zero += [_exact_rule(24, 0), _exact_rule(25, 1),
                 _exact_rule(26, 0x41484252)]
    return {"word_count": 27, "outcomes": [{
        "id": "bounded_settled_marker_read", "rules": rules,
    }, {
        "id": "all_zero_response", "rules": all_zero,
    }]}


def _control_contract():
    rules = [_exact_rule(word, 0) for word in range(24)]
    rules += [_exact_rule(24, 0), _exact_rule(25, 1),
              _exact_rule(26, 0x41484252)]
    return {"word_count": 27, "outcomes": [{
        "id": "idle", "rules": rules,
    }, {
        "id": "inverted_markers", "rules": [
            _exact_rule(24, 1), _exact_rule(25, 0),
            _exact_rule(26, 0x41484252),
        ],
    }]}


def _classify(contract, words):
    return H.classify_observation(contract, words)["classification"]


def test_r4_target_from_start_and_r3_shaped_prefix_are_accepted():
    target = _active_words([9] * 64, [8] * 64, [9] * 64)
    assert _classify(_active_contract(), target) == (
        "bounded_settled_marker_read")

    r3_shaped = _active_words(
        [8] * 4 + [9] * 60,
        [9] * 4 + [8] * 60,
        [8] * 4 + [9] * 60,
    )
    assert _classify(_active_contract(), r3_shaped) == (
        "bounded_settled_marker_read")


def test_r4_control_all_zero_trace_is_accepted():
    control = _active_words([0] * 64, [0] * 64, [0] * 64)
    assert _classify(_control_contract(), control) == "idle"


@pytest.mark.parametrize("words", [
    _active_words([8] * 64, [9] * 64, [8] * 64),
    _active_words([9] * 63 + [8], [8] * 64, [9] * 64),
    _active_words(([9, 8] * 32), ([8, 9] * 32), ([9, 8] * 32)),
    _active_words([1] * 64, [0] * 64, [1] * 64),
])
def test_r4_rejects_stale_late_transition_oscillation_and_missing_valid(words):
    assert _classify(_active_contract(), words) == "UNCLASSIFIED"


def test_r4_rejects_nonzero_control_trace():
    words = _active_words([0] * 64, [0] * 64, [0] * 64)
    words[0] = 1
    assert _classify(_control_contract(), words) == "UNCLASSIFIED"


@pytest.mark.parametrize("index,value", [
    (24, 1), (25, 0), (26, 0x41484253),
])
def test_r4_rejects_marker_or_tag_mutation(index, value):
    words = _active_words([9] * 64, [8] * 64, [9] * 64)
    words[index] = value
    assert _classify(_active_contract(), words) == "UNCLASSIFIED"


def test_r4_packing_capacity_and_overflow_contract_are_exact():
    samples = list(range(16)) * 4
    assert _pack_trace(samples) == [
        0x76543210, 0xfedcba98, 0x76543210, 0xfedcba98,
        0x76543210, 0xfedcba98, 0x76543210, 0xfedcba98,
    ]
    assert 3 * 8 + 3 == 27
    assert 27 <= 32

    source = SOURCE.read_text(encoding="utf-8")
    assert "#define TRACE_SAMPLES_PER_PHASE 64u" in source
    assert "#define TRACE_WORDS_PER_PHASE    8u" in source
    assert "#define OBSERVATION_WORDS       27u" in source
    assert "if (capacity < OBSERVATION_WORDS)" in source
    assert "return capacity + 1u;" in source
    assert "sample = *status & 0x0fu;" in source
    assert "trace[index >> 3] |= sample << ((index & 7u) * 4u);" in source
    assert "index < 128u" in source
    assert "words[26] = 0x41484252u" in source
