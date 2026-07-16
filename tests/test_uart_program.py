import pytest

from agamemnon import uart_program as U


class MemoryLoader:
    def __init__(self):
        self.memory = bytearray((i * 17 + 3) & 0xff for i in range(U.FLASH_SIZE))
        self.erased = []
        self.writes = []

    def read_memory(self, addr, size):
        offset = addr - U.FLASH_BASE
        return bytes(self.memory[offset:offset + size])

    def erase_pages(self, pages):
        self.erased.extend(pages)
        for page in pages:
            start = page * U.SECTOR_SIZE
            self.memory[start:start + U.SECTOR_SIZE] = b"\xff" * U.SECTOR_SIZE

    def write_memory(self, addr, data):
        offset = addr - U.FLASH_BASE
        self.memory[offset:offset + len(data)] = data
        self.writes.append((addr, bytes(data)))


class ProtocolBridge:
    def __init__(self, responses):
        self.responses = bytearray(responses)
        self.transmitted = []

    def uart_tx(self, data):
        self.transmitted.append(bytes(data))

    def uart_rx(self, count, timeout=1.0):
        data = bytes(self.responses[:count])
        del self.responses[:count]
        return data


def test_uart_flash_requires_full_backup_path():
    with pytest.raises(ValueError, match="mandatory"):
        U.flash_image(MemoryLoader(), b"abc", U.FLASH_BASE, "")


def test_uart_flash_preserves_uncovered_sector_bytes(tmp_path):
    loader = MemoryLoader()
    original = bytes(loader.memory)
    address = U.FLASH_BASE + U.SECTOR_SIZE - 4
    image = b"abcdefghij"
    backup = tmp_path / "full.bin"

    pages = U.flash_image(loader, image, address, str(backup))

    assert pages == [0, 1]
    assert backup.read_bytes() == original
    assert loader.erased == [0, 1]
    assert [len(data) for _, data in loader.writes] == [2 * U.SECTOR_SIZE]
    offset = address - U.FLASH_BASE
    assert loader.memory[offset:offset + len(image)] == image
    assert loader.memory[:offset] == original[:offset]
    assert loader.memory[offset + len(image):2 * U.SECTOR_SIZE] == original[offset + len(image):2 * U.SECTOR_SIZE]


def test_extended_read_packet_format():
    # command ACK, address ACK, length ACK, then four data bytes
    bridge = ProtocolBridge(bytes((U.ACK, U.ACK, U.ACK)) + b"data")
    loader = U.AG32Bootloader(bridge)

    assert loader.read_memory(0x80001234, 4) == b"data"
    assert bridge.transmitted == [
        b"\x13\xec",
        b"\x80\x00\x12\x34\xa6",
        b"\x00\x03\x03",
    ]


def test_extended_erase_packet_format():
    bridge = ProtocolBridge(bytes((U.ACK, U.ACK)))
    loader = U.AG32Bootloader(bridge)

    loader.erase_pages([2, 3])

    assert bridge.transmitted == [b"\x44\xbb", b"\x00\x01\x00\x02\x00\x03\x00"]


def test_go_packet_format():
    bridge = ProtocolBridge(bytes((U.ACK, U.ACK)))
    loader = U.AG32Bootloader(bridge)
    loader.commands = {U.CMD_GO}

    loader.go(0x80010000)

    assert bridge.transmitted == [b"\x21\xde", b"\x80\x01\x00\x00\x81"]


def test_extended_write_packet_format():
    bridge = ProtocolBridge(bytes((U.ACK, U.ACK, U.ACK)))
    loader = U.AG32Bootloader(bridge)

    loader.write_memory(0x80000100, b"abc")

    payload = b"\x00\x02abc"
    assert bridge.transmitted == [
        b"\x33\xcc",
        b"\x80\x00\x01\x00\x81",
        payload + bytes((U._xor(payload),)),
    ]


def test_empty_pico_rx_response_means_timeout_not_bad_protocol():
    bridge = U.PicoUartBridge.__new__(U.PicoUartBridge)
    bridge.command = lambda *args, **kwargs: "RX"
    assert bridge.uart_rx(1, 0.01) == b""


def test_verify_failure_is_reported_after_program(tmp_path):
    class CorruptLoader(MemoryLoader):
        reads = 0

        def read_memory(self, addr, size):
            data = super().read_memory(addr, size)
            self.reads += 1
            if self.reads == 2:
                return bytes((data[0] ^ 1,)) + data[1:]
            return data

    with pytest.raises(U.UartProgrammingError, match="verify failed at"):
        U.flash_image(
            CorruptLoader(), b"hello", U.FLASH_BASE + 10, str(tmp_path / "backup.bin")
        )
