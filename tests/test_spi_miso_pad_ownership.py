"""SPI controllers share a pad enable, not their distinct receive terminals."""
from types import SimpleNamespace

import pytest

from agamemnon.engine.features.mcu_gpio import FEATURE, mark_spi_miso_pad_input

KEY = (18, 13, 7, 18, 9, 56)


def physical():
    return SimpleNamespace(pad_input_edge={KEY: ('CFG_RMUX9', [26,29], [(92,64)], [])},
                           pad_input_used=set())


@pytest.mark.parametrize('controller', [0,1])
def test_both_receivers_request_the_same_owned_enable(controller):
    module = {'cells': {'miso': {'type': 'MCU_SPI%d_MISO_INPUT' % controller}}}
    state = physical()
    mark_spi_miso_pad_input(module, state)
    assert state.pad_input_used == {(KEY, ((92,64),), ())}
    mark_spi_miso_pad_input(module, state)
    assert len(state.pad_input_used) == 1


@pytest.mark.parametrize('controller', [0,1])
@pytest.mark.parametrize('missing', ['state','codeword'])
def test_missing_physical_binding_refused(controller, missing):
    module = {'cells': {'miso': {'type': 'MCU_SPI%d_MISO_INPUT' % controller}}}
    state = None if missing == 'state' else physical()
    if state is not None:
        state.pad_input_edge.clear()
    with pytest.raises(SystemExit, match='SPI MISO input'):
        mark_spi_miso_pad_input(module, state)


def test_unrelated_logic_does_not_request_enable():
    state = physical()
    mark_spi_miso_pad_input({'cells': {'tx': {'type':'MCU_SPI0_MOSI_OUTPUT'}}}, state)
    assert not state.pad_input_used


@pytest.mark.parametrize('controller', [0,1])
def test_receive_fence_precedes_enable_request(controller):
    state = physical()
    with pytest.raises(SystemExit, match='VP-AGM-008'):
        FEATURE.prepare({'cells': {'rx': {'type':'MCU_SPI%d_MISO_INPUT' % controller}}}, {}, state)
    assert not state.pad_input_used
