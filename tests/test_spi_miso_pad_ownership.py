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
def test_prepare_admits_corrected_receive_enable(controller):
    state = physical()
    FEATURE.prepare({'cells': {'rx': {'type':'MCU_SPI%d_MISO_INPUT' % controller}}}, {}, state)
    assert state.pad_input_used == {(KEY, ((92,64),), ())}


@pytest.mark.parametrize('controller', [0,1])
@pytest.mark.parametrize('missing', ['state','codeword'])
def test_prepare_still_refuses_missing_physical_binding(controller, missing):
    state = None if missing == 'state' else physical()
    if state is not None:
        state.pad_input_edge.clear()
    with pytest.raises(SystemExit, match='SPI MISO input'):
        FEATURE.prepare({'cells': {'rx': {'type':'MCU_SPI%d_MISO_INPUT' % controller}}}, {}, state)


@pytest.mark.parametrize('digest', [
    'b883504de4b28f3175c641d944d63899a262a8a880ba506c0071195193ef7ea6',
    'e6e1cf153eb519368a91c45737a16c25aeb6bc75462710734d1663f9b3c09fca'])
def test_old_stuck_high_spi_images_remain_rejected(digest):
    from agamemnon.engine.silicon_negatives import refuse_known_silicon_negative_digest
    with pytest.raises(SystemExit, match='VP-AGM-008'):
        refuse_known_silicon_negative_digest(digest)
