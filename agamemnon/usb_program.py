"""AG32 flash-resident USB CDC uploader transport.

The uploader speaks the same byte protocol as the AG32 serial loader, but the
bytes travel directly over a CDC ACM port rather than through the Pico bridge.
It is an application in main flash, not mask-ROM recovery.
"""

from __future__ import annotations

import time

from .uart_program import (
    AG32Bootloader,
    CMD_GO,
    FLASH_BASE,
    FLASH_SIZE,
    UartProgrammingError,
    _validate_flash_span,
    _write_backup,
    flash_image,
)


USB_VID = 0xCAFE
USB_PID = 0x4001


def find_usb_port(port=None):
    if port:
        return port
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise UartProgrammingError(
            "pyserial is required; install with 'pip install -e .[programming]'"
        ) from exc
    candidates = []
    for item in list_ports.comports():
        text = " ".join(str(x or "") for x in (
            item.description, item.manufacturer, item.product
        )).lower()
        if ((item.vid, item.pid) == (USB_VID, USB_PID)
                or "agm uploader" in text or "uploader cdc" in text):
            candidates.append(item.device)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise UartProgrammingError(
            "no AG32 USB CDC uploader found; install the loader first or pass --port"
        )
    raise UartProgrammingError(
        "multiple AG32 USB uploaders found (" + ", ".join(candidates) + "); pass --port"
    )


class USBSerialBridge:
    """Raw-byte bridge expected by :class:`AG32Bootloader`."""

    def __init__(self, port=None):
        try:
            import serial
        except ImportError as exc:
            raise UartProgrammingError(
                "pyserial is required; install with 'pip install -e .[programming]'"
            ) from exc
        self.port = find_usb_port(port)
        try:
            self.serial = serial.Serial(self.port, 115200, timeout=2, write_timeout=3)
        except serial.SerialException as exc:
            raise UartProgrammingError(f"cannot open AG32 USB uploader {self.port}: {exc}") from exc
        # Windows can expose the COM port before TinyUSB has returned to the
        # uploader task after configuration. The vendor client also allows a
        # settling interval before its 0x7f synchronization byte.
        time.sleep(0.75)

    def close(self):
        if getattr(self, "serial", None) is not None:
            self.serial.close()
            self.serial = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def enter_rom(self):
        # There are no boot pins on this transport. The resident loader is
        # already waiting for the synchronization byte.
        self.flush_uart()

    def run_application(self):
        # Kept for bridge compatibility. USB callers explicitly use GO.
        return None

    def flush_uart(self):
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def uart_tx(self, data):
        self.serial.write(data)
        self.serial.flush()

    def uart_rx(self, count, timeout=1.0):
        old_timeout = self.serial.timeout
        self.serial.timeout = timeout
        try:
            output = bytearray()
            while len(output) < count:
                piece = self.serial.read(count - len(output))
                if not piece:
                    break
                output.extend(piece)
            return bytes(output)
        finally:
            self.serial.timeout = old_timeout


def connect(port=None):
    bridge = USBSerialBridge(port)
    loader = AG32Bootloader(bridge)
    try:
        # Do not use the ROM bridge's 0x7f/0x7f80 fallback. The second byte of
        # that fallback is a real command byte to the already-running CDC
        # loader and can contaminate its parser when enumeration was merely
        # slow. A NACK to INIT is normal when this loader is already synced.
        bridge.flush_uart()
        response = b""
        for _ in range(3):
            bridge.uart_tx(b"\x7f")
            response = bridge.uart_rx(1, 2.0)
            if response:
                break
            time.sleep(0.1)
        if not response or response[0] not in (0x79, 0x1F):
            raise UartProgrammingError("AG32 USB uploader did not answer INIT")
        last_error = None
        for _ in range(2):
            try:
                loader.get_commands()
                break
            except UartProgrammingError as exc:
                last_error = exc
        else:
            raise last_error
    except Exception:
        bridge.close()
        raise
    return bridge, loader


def identify(port=None):
    bridge, loader = connect(port)
    try:
        device_id = loader.get_id()
        return (
            f"loader v{loader.version >> 4}.{loader.version & 0xf}, "
            f"device ID 0x{device_id.hex()} via {bridge.port}"
        )
    finally:
        bridge.close()


def cmd_usb_probe(args):
    print("AG32 USB CDC " + identify(args.port))


def cmd_usb_backup(args):
    bridge, loader = connect(args.port)
    try:
        data = loader.read_memory(FLASH_BASE, FLASH_SIZE)
        _write_backup(args.output, data)
        print(f"backed up {len(data)} bytes to {args.output} via USB CDC")
    finally:
        bridge.close()


def cmd_usb_flash(args):
    if not args.backup:
        raise ValueError("USB flash writes require --backup")
    with open(args.image, "rb") as source:
        image = source.read()
    addr = int(args.addr, 0)
    _validate_flash_span(addr, len(image))
    bridge, loader = connect(args.port)
    try:
        pages = flash_image(loader, image, addr, args.backup)
        print(
            f"verified {len(image)} payload bytes in {len(pages)} preserved 4-KiB "
            f"sector(s) via USB CDC; full backup: {args.backup}"
        )
    finally:
        bridge.close()


def cmd_usb_go(args):
    address = int(args.addr, 0)
    bridge, loader = connect(args.port)
    try:
        loader.go(address)
        print(f"GO 0x{address:08x} accepted via {bridge.port}")
    finally:
        bridge.close()
