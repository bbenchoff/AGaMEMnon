"""Program AG32 main flash through its mask-ROM UART0 bootloader.

The physical transport is a Raspberry Pi Pico 2 running the companion sketch
in ``pico/ag32_uart_programmer``.  USB carries a small line protocol to the
Pico; the Pico controls BOOT0/BOOT1/NRST and forwards binary boot-ROM traffic
on UART0 at 460800 8N1.

Persistent writes are deliberately conservative: a full-flash backup is
mandatory, touched 4-KiB sectors are read/modified/written as complete units,
and every written sector is read back and compared byte-for-byte.
"""

from __future__ import annotations

import os
import struct
import time
from typing import Optional


FLASH_BASE = 0x80000000
FLASH_SIZE = 0x40000
SECTOR_SIZE = 0x1000
UART_BAUD = 460800
EXPECTED_DEVICE_ID = bytes.fromhex("40200001")

ACK = 0x79
NACK = 0x1F
BUSY = 0x76
CMD_GET = 0x00
CMD_GET_ID = 0x02
CMD_READ_EXTENDED = 0x13
CMD_GO = 0x21
CMD_WRITE_EXTENDED = 0x33
CMD_ERASE_EXTENDED = 0x44


class UartProgrammingError(RuntimeError):
    """The Pico bridge or AG32 ROM rejected a programming operation."""


def require_device_id(loader) -> bytes:
    """Identify the target before any transport command that mutates it."""
    device_id = loader.get_id()
    if device_id != EXPECTED_DEVICE_ID:
        raise UartProgrammingError(
            f"target identity mismatch: expected 0x{EXPECTED_DEVICE_ID.hex()}, "
            f"got 0x{device_id.hex()}"
        )
    return device_id


def _validate_flash_span(addr: int, size: int) -> int:
    end = addr + size
    if size <= 0 or addr < FLASH_BASE or end > FLASH_BASE + FLASH_SIZE:
        raise ValueError(
            f"range 0x{addr:08x}..0x{end:08x} is outside the 256-KiB main flash"
        )
    return end


def _xor(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def _find_pico_port() -> str:
    try:
        from serial.tools import list_ports
    except ImportError as exc:  # pragma: no cover - depends on host install
        raise UartProgrammingError(
            "pyserial is required; install with 'pip install -e .[programming]'"
        ) from exc

    candidates = []
    for port in list_ports.comports():
        text = " ".join(
            str(x or "") for x in (port.description, port.manufacturer, port.product)
        ).lower()
        if port.vid == 0x2E8A or "raspberry pi pico" in text or "pico 2" in text:
            candidates.append(port.device)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise UartProgrammingError("no Pico serial port found; pass --port explicitly")
    raise UartProgrammingError(
        "multiple Pico serial ports found (" + ", ".join(candidates) + "); pass --port"
    )


class PicoUartBridge:
    """Line-protocol client for the checked-in Pico 2 firmware."""

    def __init__(self, port: Optional[str] = None):
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on host install
            raise UartProgrammingError(
                "pyserial is required; install with 'pip install -e .[programming]'"
            ) from exc

        self.port = port or _find_pico_port()
        self.serial = serial.Serial(self.port, 115200, timeout=2, write_timeout=2)
        # Opening USB CDC does not set the target baud, but give a freshly
        # reset Pico time to enumerate and discard any stale console output.
        time.sleep(0.15)
        self.serial.reset_input_buffer()
        reply = self.command("PING")
        if not reply.startswith("AG32UART v1"):
            self.close()
            raise UartProgrammingError(
                f"{self.port} is not running the AG32 UART bridge (got {reply!r})"
            )

    def close(self):
        if getattr(self, "serial", None) is not None:
            self.serial.close()
            self.serial = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def command(self, line: str, timeout: float = 2.0) -> str:
        if self.serial is None:
            raise UartProgrammingError("Pico serial port is closed")
        old_timeout = self.serial.timeout
        self.serial.timeout = timeout
        try:
            self.serial.write((line + "\n").encode("ascii"))
            raw = self.serial.readline()
        finally:
            self.serial.timeout = old_timeout
        if not raw:
            raise UartProgrammingError(f"Pico timed out answering {line.split()[0]}")
        reply = raw.decode("ascii", errors="replace").strip()
        if reply.startswith("ERR "):
            raise UartProgrammingError(f"Pico: {reply[4:]}")
        return reply

    def enter_rom(self):
        if self.command("BOOT ENTER", timeout=3) != "OK":
            raise UartProgrammingError("unexpected BOOT ENTER response")

    def run_application(self):
        if self.command("BOOT RUN", timeout=3) != "OK":
            raise UartProgrammingError("unexpected BOOT RUN response")

    def flush_uart(self):
        if self.command("UART FLUSH") != "OK":
            raise UartProgrammingError("unexpected UART FLUSH response")

    def uart_tx(self, data: bytes):
        # Keep each USB line bounded; pauses between pieces are accepted by the
        # ROM's byte receiver and avoid relying on a large Pico USB buffer.
        for offset in range(0, len(data), 128):
            piece = data[offset:offset + 128]
            reply = self.command("UART TX " + piece.hex(), timeout=3)
            if reply != f"TX {len(piece)}":
                raise UartProgrammingError(f"unexpected UART TX response {reply!r}")

    def uart_rx(self, count: int, timeout: float = 1.0) -> bytes:
        if count < 0:
            raise ValueError("negative UART receive length")
        result = bytearray()
        while len(result) < count:
            want = min(128, count - len(result))
            timeout_ms = max(1, int(timeout * 1000))
            reply = self.command(
                f"UART RX {want} {timeout_ms}", timeout=timeout + 1.0
            )
            if reply == "RX":
                piece = b""
                result.extend(piece)
                break
            if not reply.startswith("RX "):
                raise UartProgrammingError(f"unexpected UART RX response {reply!r}")
            hex_data = reply[3:]
            try:
                piece = bytes.fromhex(hex_data)
            except ValueError as exc:
                raise UartProgrammingError(f"invalid Pico UART data {hex_data!r}") from exc
            result.extend(piece)
            if len(piece) != want:
                break
        return bytes(result)


class AG32Bootloader:
    """AG32 mask-ROM command protocol over a :class:`PicoUartBridge`."""

    def __init__(self, bridge: PicoUartBridge):
        self.bridge = bridge
        self.commands = set()

    def _read_exact(self, count: int, timeout: float = 1.0) -> bytes:
        data = self.bridge.uart_rx(count, timeout)
        if len(data) != count:
            raise UartProgrammingError(
                f"AG32 UART timeout: wanted {count} byte(s), received {len(data)}"
            )
        return data

    def _expect_ack(self, operation: str, timeout: float = 1.0):
        value = self._read_exact(1, timeout)[0]
        while value == BUSY:
            value = self._read_exact(1, timeout)[0]
        if value == NACK:
            raise UartProgrammingError(f"AG32 ROM rejected {operation} (NACK)")
        if value != ACK:
            raise UartProgrammingError(
                f"AG32 ROM returned 0x{value:02x}, expected ACK for {operation}"
            )

    def connect(self):
        # The conventional ROM autobaud byte is tried first.  Some observed
        # revisions instead consume a normal command/complement pair, so a
        # reset-bounded fallback supports that parser without contaminating
        # the first attempt's state.
        for packet in (b"\x7f", b"\x7f\x80"):
            self.bridge.enter_rom()
            self.bridge.flush_uart()
            self.bridge.uart_tx(packet)
            response = self.bridge.uart_rx(1, 0.5)
            if response and response[0] in (ACK, NACK):
                self.get_commands()
                return
        raise UartProgrammingError(
            "AG32 boot ROM did not answer; check crossed TX/RX, common ground, "
            "BOOT0 high during reset, and 3.3-V signaling"
        )

    def _begin(self, command: int, operation: str):
        self.bridge.uart_tx(bytes((command, command ^ 0xFF)))
        self._expect_ack(operation)

    def _send_address(self, addr: int, operation: str):
        raw = struct.pack(">I", addr)
        self.bridge.uart_tx(raw + bytes((_xor(raw),)))
        self._expect_ack(operation)

    def get_commands(self):
        self._begin(CMD_GET, "GET")
        length = self._read_exact(1)[0] + 1
        data = self._read_exact(length)
        self._expect_ack("GET completion")
        if not data:
            raise UartProgrammingError("empty AG32 GET response")
        self.version = data[0]
        self.commands = set(data[1:])
        required = {CMD_GET_ID, CMD_READ_EXTENDED, CMD_WRITE_EXTENDED, CMD_ERASE_EXTENDED}
        missing = required - self.commands
        if missing:
            raise UartProgrammingError(
                "AG32 ROM lacks required command(s): "
                + ", ".join(f"0x{x:02x}" for x in sorted(missing))
            )

    def get_id(self) -> bytes:
        self._begin(CMD_GET_ID, "GET_ID")
        length = self._read_exact(1)[0] + 1
        device_id = self._read_exact(length)
        self._expect_ack("GET_ID completion")
        return device_id

    def read_memory(self, addr: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("negative read length")
        output = bytearray()
        while len(output) < size:
            count = min(1024, size - len(output))
            self._begin(CMD_READ_EXTENDED, "extended read")
            self._send_address(addr + len(output), "read address")
            raw_length = struct.pack(">H", count - 1)
            self.bridge.uart_tx(raw_length + bytes((_xor(raw_length),)))
            self._expect_ack("read length")
            output.extend(self._read_exact(count, max(1.0, count / 20000.0)))
        return bytes(output)

    def go(self, addr: int):
        if self.commands and CMD_GO not in self.commands:
            raise UartProgrammingError("connected loader does not advertise GO (0x21)")
        self._begin(CMD_GO, "GO")
        self._send_address(addr, "GO address")

    def erase_pages(self, pages):
        pages = list(pages)
        if not pages:
            return
        if any(page < 0 or page >= FLASH_SIZE // SECTOR_SIZE for page in pages):
            raise ValueError("flash page number outside main flash")
        self._begin(CMD_ERASE_EXTENDED, "extended erase")
        payload = bytearray(struct.pack(">H", len(pages) - 1))
        for page in pages:
            payload.extend(struct.pack(">H", page))
        payload.append(_xor(payload))
        self.bridge.uart_tx(bytes(payload))
        self._expect_ack("page erase", timeout=20.0)

    def write_memory(self, addr: int, data: bytes):
        # 256-byte packets are well inside the AG32 extended command's 4-KiB
        # limit and keep retry/failure boundaries small.
        for offset in range(0, len(data), 256):
            piece = data[offset:offset + 256]
            self._begin(CMD_WRITE_EXTENDED, "extended write")
            self._send_address(addr + offset, "write address")
            raw_length = struct.pack(">H", len(piece) - 1)
            payload = raw_length + piece
            self.bridge.uart_tx(payload + bytes((_xor(payload),)))
            self._expect_ack("flash program", timeout=5.0)


def _write_backup(path: str, data: bytes):
    with open(path, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def flash_image(loader: AG32Bootloader, image: bytes, addr: int, backup_path: str):
    """Back up, sector-preserve, program, and verify one main-flash payload."""
    end = _validate_flash_span(addr, len(image))
    if not backup_path:
        raise ValueError("a full-flash --backup path is mandatory for UART writes")

    full_backup = loader.read_memory(FLASH_BASE, FLASH_SIZE)
    if len(full_backup) != FLASH_SIZE:
        raise UartProgrammingError("full flash backup was truncated")
    _write_backup(backup_path, full_backup)

    first_sector = (addr - FLASH_BASE) // SECTOR_SIZE
    last_sector = (end - 1 - FLASH_BASE) // SECTOR_SIZE
    pages = list(range(first_sector, last_sector + 1))
    sector_addr = FLASH_BASE + first_sector * SECTOR_SIZE
    sector_data = bytearray(
        full_backup[first_sector * SECTOR_SIZE:(last_sector + 1) * SECTOR_SIZE]
    )
    offset = addr - sector_addr
    sector_data[offset:offset + len(image)] = image

    loader.erase_pages(pages)
    loader.write_memory(sector_addr, bytes(sector_data))
    actual = loader.read_memory(sector_addr, len(sector_data))
    if actual != bytes(sector_data):
        for index, (want, got) in enumerate(zip(sector_data, actual)):
            if want != got:
                bad_addr = sector_addr + index
                raise UartProgrammingError(
                    f"verify failed at 0x{bad_addr:08x}: wrote 0x{want:02x}, read 0x{got:02x}"
                )
        raise UartProgrammingError("verify failed: readback length differs")
    return pages


def _connect(args):
    bridge = PicoUartBridge(args.port)
    loader = AG32Bootloader(bridge)
    try:
        loader.connect()
    except Exception:
        bridge.close()
        raise
    return bridge, loader


def cmd_uart_probe(args):
    bridge, loader = _connect(args)
    try:
        device_id = require_device_id(loader)
        print(
            f"AG32 boot ROM v{loader.version >> 4}.{loader.version & 0xf}, "
            f"device ID 0x{device_id.hex()} via {bridge.port}"
        )
    finally:
        try:
            bridge.run_application()
        finally:
            bridge.close()


def cmd_uart_backup(args):
    bridge, loader = _connect(args)
    try:
        require_device_id(loader)
        data = loader.read_memory(FLASH_BASE, FLASH_SIZE)
        _write_backup(args.output, data)
        print(f"backed up {len(data)} bytes to {args.output}")
    finally:
        try:
            bridge.run_application()
        finally:
            bridge.close()


def cmd_uart_flash(args):
    with open(args.image, "rb") as source:
        image = source.read()
    addr = int(args.addr, 0)
    _validate_flash_span(addr, len(image))

    bridge, loader = _connect(args)
    succeeded = False
    try:
        require_device_id(loader)
        pages = flash_image(loader, image, addr, args.backup)
        succeeded = True
        print(
            f"verified {len(image)} payload bytes in {len(pages)} preserved 4-KiB "
            f"sector(s); full backup: {args.backup}"
        )
    finally:
        # A partially programmed image stays safely in the ROM recovery path.
        # Only a complete byte-verified transaction is allowed to boot flash.
        try:
            if succeeded:
                bridge.run_application()
                print("BOOT0 low; AG32 reset into main flash")
            else:
                print("write did not complete; leaving AG32 in serial-ROM recovery")
        finally:
            bridge.close()


def cmd_uart_reset(args):
    with PicoUartBridge(args.port) as bridge:
        bridge.run_application()
    print("BOOT0 low; AG32 reset into main flash")
