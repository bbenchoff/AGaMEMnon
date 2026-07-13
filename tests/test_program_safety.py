"""Pure, hardware-free safety checks for flash range validation."""
import pytest

from agamemnon import program as P


def test_sectors_for_empty_is_empty():
    assert P._sectors_for(P.FLASH_BASE + 0x8100, 0) == []


def test_flash_span_accepts_exact_device():
    assert P._validate_flash_span(P.FLASH_BASE, P.FLASH_SIZE) == P.FLASH_BASE + P.FLASH_SIZE


@pytest.mark.parametrize("addr,size", [
    (P.FLASH_BASE, 0),
    (P.FLASH_BASE - 1, 1),
    (P.FLASH_BASE + P.FLASH_SIZE - 1, 2),
    (P.FLASH_BASE + P.FLASH_SIZE, 1),
])
def test_flash_span_rejects_empty_and_overflow(addr, size):
    with pytest.raises(ValueError):
        P._validate_flash_span(addr, size)
