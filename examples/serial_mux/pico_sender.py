# MicroPython script for a Raspberry Pi Pico wired to the AG32 dev board.
#
# Three PIO state machines send overlapping A, B, and C frames. A fourth
# decodes the buffered, round-robin output and echoes it to the USB console.
#
# Default wiring (matches the AG32-Docs Pico test rig):
#   Pico GP0 -> AG32 PIN_10  (rx_a, stream of 'A')
#   Pico GP1 -> AG32 PIN_11  (rx_b, stream of 'B')
#   Pico GP5 -> AG32 PIN_15  (rx_c, stream of 'C')
#   Pico GP6 <- AG32 PIN_16  (muxed output)
#   Common GND between the boards.

import rp2
import time
from machine import Pin

RX_BAUD = 9600
TX_BAUD = 115200

SEND_PINS = {0: ord("A"), 1: ord("B"), 5: ord("C")}
RECV_PIN = 6


@rp2.asm_pio(sideset_init=rp2.PIO.OUT_HIGH, out_init=rp2.PIO.OUT_HIGH,
             out_shiftdir=rp2.PIO.SHIFT_RIGHT)
def uart_tx():
    # 8N1 transmit, 8 PIO cycles per bit.
    pull()           .side(1)  [7]   # idle/stop while waiting for data
    set(x, 7)        .side(0)  [7]   # start bit
    label("bitloop")
    out(pins, 1)               [6]   # data bits, LSB first
    jmp(x_dec, "bitloop")


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT)
def uart_rx():
    # 8N1 receive, 8 PIO cycles per bit, sampled mid-bit.
    label("start")
    wait(0, pin, 0)                  # start bit edge
    set(x, 7)                  [10]  # skip to the middle of data bit 0
    label("bitloop")
    in_(pins, 1)
    jmp(x_dec, "bitloop")      [6]
    jmp(pin, "good")                 # stop bit must be high
    wait(1, pin, 0)                  # framing error: resync on idle
    jmp("start")
    label("good")
    push(block)


def main():
    senders = []
    for sm_id, (gp, char) in enumerate(sorted(SEND_PINS.items())):
        sm = rp2.StateMachine(sm_id, uart_tx, freq=8 * RX_BAUD,
                              sideset_base=Pin(gp), out_base=Pin(gp))
        sm.active(1)
        senders.append((sm, char))

    rx_pin = Pin(RECV_PIN, Pin.IN, Pin.PULL_UP)
    rx = rp2.StateMachine(4, uart_rx, freq=8 * TX_BAUD,
                          in_base=rx_pin, jmp_pin=rx_pin)
    rx.active(1)

    print("sending overlapping A/B/C at %d baud; receiving at %d baud" %
          (RX_BAUD, TX_BAUD))
    while True:
        # Queue all three state machines back-to-back. At 9600 baud their
        # start edges are within a fraction of one input bit, so the frames
        # overlap while the fabric receivers capture them independently.
        for sm, char in senders:
            sm.put(char)

        for _ in range(3):
            byte = (rx.get() >> 24) & 0xFF
            print(chr(byte), end="")


main()
