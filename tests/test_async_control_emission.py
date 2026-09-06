"""Asynchronous configuration ownership and explicit experimental admission."""
import pytest

from agamemnon.engine.bit_ownership import BitOwnershipTrace
from agamemnon.engine.claim_policy import ClaimPolicyError, evaluate_policy
from agamemnon.engine.features.async_control_routes import plan_routed_async_controls, validate_async_route_graph
from agamemnon.engine.features.clocks import FEATURE as CLOCKS, ClockState
from agamemnon.engine.features.core_logic import FEATURE as LOGIC, CoreLogicState
from agamemnon.engine.features.protocol import BitstreamContext
from agamemnon.engine.registry import OPTION_CLAIMS, options_from
from test_async_control_routes import _module


OPTION = 'AGAMEMNON_ASYNC_CONTROL_CONFIG'


def test_async_configuration_cannot_inherit_release_qualification():
    with pytest.raises(ClaimPolicyError, match='requires release maturity'):
        evaluate_policy(options_from({OPTION: '1'}))
    with pytest.raises(ClaimPolicyError, match='explicit feature ID'):
        evaluate_policy(options_from({OPTION: '1', 'AGAMEMNON_STRICT_POLICY': 'experimental-strict'}))
    decision = evaluate_policy(options_from({OPTION: '1', 'AGAMEMNON_STRICT_POLICY': 'experimental-strict',
                                             'AGAMEMNON_EXPERIMENTAL_FEATURES': OPTION}))
    claim = OPTION_CLAIMS[OPTION]
    assert claim.evidence_tier == 'differentially_validated'
    assert claim.approved_by is None
    assert 'silicon behavior unqualified' in claim.claim_scope
    assert decision.policy == 'experimental-strict'


@pytest.mark.parametrize('initial', (0, 255))
def test_explicit_control_configuration_replaces_only_clock_ground_default(initial):
    # Deliberately start with both possible stale values. Ground must be cleared
    # as well as set; a set-only overlay would silently preserve active reset.
    image = bytearray([initial] * 512)
    logic = CoreLogicState(async_writes={(100, 8): False, (101, 2): True})
    clocks = ClockState(sets=[(100, 8), (200, 4)], async_ground_bits={(100, 8)})
    CLOCKS.delegate_async_ground(clocks, logic.async_writes)
    trace = BitOwnershipTrace(len(image))
    clock_writer = trace.bind('clocks', CLOCKS.writable_bits(clocks))
    logic_writer = trace.bind('core_logic', LOGIC.writable_bits(logic))
    options = options_from({})
    CLOCKS.emit_bitstream(BitstreamContext(image, {}, None, options, clock_writer, clocks))
    LOGIC.emit_register_modes(BitstreamContext(image, {}, None, options, logic_writer, logic))
    assert image[100] == (initial & ~8)
    assert image[101] == (initial | 2)
    assert image[200] == (initial | 4)
    assert image[99] == initial


def test_async_configuration_cannot_steal_an_active_clock_bit():
    clocks = ClockState(sets=[(100, 8), (200, 4)], async_ground_bits={(100, 8)})
    with pytest.raises(ValueError, match='active clock field'):
        CLOCKS.delegate_async_ground(clocks, {(200, 4): False})
    assert clocks.sets == [(100, 8), (200, 4)]


def test_emission_requires_graph_backing_even_for_a_valid_segment_plan():
    module = _module()
    plan = plan_routed_async_controls(module)
    assert plan.pips == frozenset({
        'X14Y8_RMUX04.X14Y8_CtrlMUX00',
        'X14Y8_CtrlMUX00.X14Y8_TileAsyncMUX00',
        'X14Y8_alta_asyncctrl00.X14Y8_AsyncMUX00',
    })
    with pytest.raises(ValueError, match='validated device graph'):
        validate_async_route_graph(module, plan, None)
