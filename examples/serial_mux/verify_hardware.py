#!/usr/bin/env python3
"""Verify overlapping serial_mux traffic with the AG32-Docs Pico fixture.

This checker asks the fixture for its raw timestamped transition trace and
independently decodes it on the host with a fractional bit period.  That also
detects old fixture firmware whose integer-microsecond decoder skipped the
start of a back-to-back 115200-baud frame.
"""

import argparse
import re
import sys
import time

import serial


TRACE_RE = re.compile(r"^TRACE start=([01])(?:\s+(.*))?$")


def decode_trace(line, rx_baud, tx_baud, expected_frames=3):
    match = TRACE_RE.match(line.strip())
    if not match:
        raise ValueError("not a UARTMUX TRACE line: %r" % line)
    events = [(0.0, int(match.group(1)))]
    for token in (match.group(2) or "").split():
        stamp, level = token.split(":", 1)
        events.append((float(stamp), int(level)))

    def level_at(stamp):
        level = events[0][1]
        for when, new_level in events[1:]:
            if when > stamp:
                break
            level = new_level
        return level

    falling = []
    previous = events[0][1]
    for when, level in events[1:]:
        if previous and not level:
            falling.append(when)
        previous = level

    input_bit_us = 1_000_000.0 / rx_baud
    output_bit_us = 1_000_000.0 / tx_baud
    search_after = 8.0 * input_bit_us
    decoded = []
    for _ in range(expected_frames):
        try:
            start = next(when for when in falling if when >= search_after)
        except StopIteration as exc:
            raise ValueError("missing output start edge after %.3f us" % search_after) from exc
        value = 0
        for bit in range(8):
            value |= level_at(start + (1.5 + bit) * output_bit_us) << bit
        if not level_at(start + 9.5 * output_bit_us):
            raise ValueError("low stop bit for frame %d at %.3f us" % (len(decoded), start))
        decoded.append(value)
        # Data-bit falling edges end before 9 bit-times.  Starting the next
        # search there finds a zero-gap following start without rounding past it.
        search_after = start + 9.0 * output_bit_us
    return bytes(decoded)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Pico fixture serial port, for example COM6")
    parser.add_argument("--frames", type=int, default=100,
                        help="overlapping A/B/C transactions to verify (default: 100)")
    parser.add_argument("--rx-baud", type=int, default=9600)
    parser.add_argument("--tx-baud", type=int, default=115200)
    args = parser.parse_args(argv)
    if args.frames < 1 or args.frames > 10000:
        parser.error("--frames must be in 1..10000")
    if args.tx_baud % args.rx_baud:
        parser.error("the Pico fixture requires an integer TX/RX baud ratio")
    ratio = args.tx_baud // args.rx_baud
    if ratio < 1 or ratio > 16:
        parser.error("the Pico fixture requires a TX/RX ratio in 1..16")

    command = "UARTMUX %d %d %d trace" % (args.frames, args.rx_baud, ratio)
    traces = []
    firmware_summary = ""
    with serial.Serial(args.port, 115200, timeout=0.5) as port:
        time.sleep(1.2)
        port.reset_input_buffer()
        port.write((command + "\n").encode("ascii"))
        port.flush()
        deadline = time.time() + max(15.0, args.frames * 0.08)
        while time.time() < deadline:
            line = port.readline().decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith("TRACE start="):
                traces.append(line)
            if "pass=" in line:
                firmware_summary = line
                break

    failures = []
    for index, trace in enumerate(traces):
        try:
            got = decode_trace(trace, args.rx_baud, args.tx_baud)
        except ValueError as exc:
            failures.append((index, str(exc), trace))
            continue
        if got != b"ABC":
            failures.append((index, "decoded %r" % got, trace))

    print("command: %s" % command)
    print("host fractional decoder: %d/%d exact ABC" %
          (len(traces) - len(failures), args.frames))
    if firmware_summary:
        print("fixture decoder: %s" % firmware_summary)
    for index, reason, trace in failures[:10]:
        print("  frame %d: %s" % (index, reason))
        print("    %s" % trace)
    if len(traces) != args.frames:
        print("error: received %d/%d raw traces" % (len(traces), args.frames), file=sys.stderr)
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
