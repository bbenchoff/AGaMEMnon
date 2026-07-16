from types import SimpleNamespace

from agamemnon import usb_program as USB
from agamemnon import uart_program as U


class FakeUSBBridge:
    instance = None

    def __init__(self, port=None):
        self.port = port or "COM7"
        commands = bytes((
            0x21, 0x00, 0x01, 0x02, 0x13, 0x33, 0x44, 0x21,
            0x63, 0x73, 0x82, 0x92, 0xA2, 0xA3, 0xA1,
        ))
        self.responses = bytearray(
            bytes((U.ACK, U.ACK, 14)) + commands + bytes((U.ACK,))
        )
        self.transmitted = []
        self.closed = False
        FakeUSBBridge.instance = self

    def flush_uart(self):
        pass

    def uart_tx(self, data):
        self.transmitted.append(bytes(data))

    def uart_rx(self, count, timeout=1.0):
        result = bytes(self.responses[:count])
        del self.responses[:count]
        return result

    def close(self):
        self.closed = True


def test_usb_connect_uses_single_byte_init_not_rom_fallback(monkeypatch):
    monkeypatch.setattr(USB, "USBSerialBridge", FakeUSBBridge)
    bridge, loader = USB.connect("COM7")
    try:
        assert loader.version == 0x21
        assert FakeUSBBridge.instance.transmitted[0] == b"\x7f"
        assert b"\x7f\x80" not in FakeUSBBridge.instance.transmitted
        assert FakeUSBBridge.instance.transmitted[1] == b"\x00\xff"
    finally:
        bridge.close()


def test_usb_flash_requires_backup_before_connect(tmp_path, monkeypatch):
    image = tmp_path / "app.bin"
    image.write_bytes(b"abc")
    called = False

    def forbidden_connect(port=None):
        nonlocal called
        called = True
        raise AssertionError("must reject before opening hardware")

    monkeypatch.setattr(USB, "connect", forbidden_connect)
    try:
        USB.cmd_usb_flash(SimpleNamespace(
            image=str(image), addr="0x80010000", backup=None, port=None
        ))
    except ValueError as exc:
        assert "backup" in str(exc)
    else:
        raise AssertionError("missing backup was accepted")
    assert not called
