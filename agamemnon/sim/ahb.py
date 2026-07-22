"""Small AHB-Lite slave oracle with explicit address/data-phase behavior.

The model is independent of vendor simulation libraries.  It is intended for
scoreboards and protocol tests of fabric slaves attached to the AG32 external
AHB window, not as a cycle model of the MCU hard block.
"""
from __future__ import annotations

from dataclasses import dataclass


HTRANS_IDLE = 0
HTRANS_BUSY = 1
HTRANS_NONSEQ = 2
HTRANS_SEQ = 3


@dataclass(frozen=True)
class AhbInputs:
    select: bool = False
    trans: int = HTRANS_IDLE
    address: int = 0
    write: bool = False
    size: int = 2
    burst: int = 0
    wdata: int = 0
    ready: bool = True


@dataclass(frozen=True)
class AhbOutputs:
    rdata: int
    readyout: bool
    resp: bool


class AhbSlaveModel:
    """Word-backed AHB-Lite slave supporting byte, halfword, and word access."""

    def __init__(self, *, base=0x60000000, words=16, wait_states=0):
        if words <= 0 or wait_states < 0:
            raise ValueError("words must be positive and wait_states non-negative")
        self.base = int(base)
        self.words = [0] * int(words)
        self.wait_states = int(wait_states)
        self._active = None
        self._wait = 0

    def _decode(self, transfer):
        offset = transfer.address - self.base
        bytes_per_transfer = 1 << transfer.size if 0 <= transfer.size <= 2 else 0
        valid = (
            bytes_per_transfer != 0
            and 0 <= offset < len(self.words) * 4
            and offset % bytes_per_transfer == 0
            and offset + bytes_per_transfer <= len(self.words) * 4
        )
        return valid, offset, bytes_per_transfer

    def outputs(self):
        if self._active is None:
            return AhbOutputs(0, True, False)
        valid, offset, _ = self._decode(self._active)
        readyout = self._wait == 0
        rdata = self.words[offset // 4] if valid and not self._active.write else 0
        return AhbOutputs(rdata & 0xFFFFFFFF, readyout, readyout and not valid)

    def step(self, inputs=AhbInputs()):
        """Advance one rising edge and return outputs visible before that edge.

        The active transfer's write data is sampled from the current cycle,
        matching AHB's address/control then data-phase pipeline.
        """
        output = self.outputs()
        completing = self._active is not None and output.readyout and inputs.ready
        if self._active is not None and not output.readyout and inputs.ready:
            self._wait -= 1
        if completing:
            valid, offset, width = self._decode(self._active)
            if valid and self._active.write:
                word_index = offset // 4
                byte_lane = offset & 3
                mask = ((1 << (width * 8)) - 1) << (byte_lane * 8)
                self.words[word_index] = (
                    (self.words[word_index] & ~mask)
                    | ((inputs.wdata << (byte_lane * 8)) & mask)
                ) & 0xFFFFFFFF
            self._active = None
        can_accept = inputs.ready and output.readyout
        if can_accept and inputs.select and (inputs.trans & 2):
            self._active = inputs
            self._wait = self.wait_states
        return output

    def transact(self, *, address, write=False, size=2, data=0, burst=0):
        """Convenience single-transfer driver returning completion outputs."""
        address_phase = AhbInputs(True, HTRANS_NONSEQ, address, write, size, burst, 0, True)
        self.step(address_phase)
        while True:
            output = self.step(AhbInputs(wdata=data, ready=True))
            if output.readyout:
                return output
