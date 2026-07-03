#!/usr/bin/env python3
"""Project Agamemnon — Step 3b: open LZW codec for the AG32 `.bin` (decode + encode).

VALIDATED byte-exact vs blinky.bin (full .bin round-trips identically). The fabric `.bin` is
an 8-byte header [DEVICE_ID 0x40200001 | max_index 0x0000ffff] then a variable-width LZW
codestream:
  dw=8 -> literals 0..255, CLEAR=256, first dict code=258, codes packed MSB-first.
  initial code width = 9 bits.
  DICT RESET: when next_code reaches 1024, emit CLEAR(256) and reset (dict->256, width->9).
              => the dict never exceeds 10-bit codes here (3 resets in blinky.bin).
  WIDTH BUMP (encoder): when next_code == 2^width + 1   (decoder lags by one: == 2^width).
  NO trailing EOI; the last code is emitted and the final byte is zero-padded.

ORACLE: decode(blinky payload) -> raw; encode(raw) reproduces the payload byte-exact."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HDR = 8                       # [0:4]=DEVICE_ID 0x40200001, [4:8]=max_index 0x0000ffff
CLEAR, EOI, FIRST = 256, 257, 258
MAXW = 16

# ---- bit IO, MSB-first ----
class BitWriter:
    def __init__(self): self.acc = 0; self.nbits = 0; self.out = bytearray()
    def write(self, val, width):
        self.acc = (self.acc << width) | (val & ((1 << width) - 1)); self.nbits += width
        while self.nbits >= 8:
            self.nbits -= 8
            self.out.append((self.acc >> self.nbits) & 0xFF)
    def flush(self):
        if self.nbits: self.out.append((self.acc << (8 - self.nbits)) & 0xFF); self.nbits = 0
        return bytes(self.out)

def bits_msb(data):
    for byte in data:
        for k in range(7, -1, -1): yield (byte >> k) & 1

def decode(payload):
    gen = bits_msb(payload)
    def rd(n):
        v = 0
        for _ in range(n):
            try: v = (v << 1) | next(gen)
            except StopIteration: return None
        return v
    dic = {i: bytes([i]) for i in range(CLEAR)}; width = 9; nxt = FIRST
    out = bytearray(); prev = None
    while True:
        code = rd(width)
        if code is None or code == EOI: break
        if code == CLEAR:
            dic = {i: bytes([i]) for i in range(CLEAR)}; width = 9; nxt = FIRST; prev = None; continue
        entry = dic[code] if code in dic else (prev + prev[:1] if code == nxt else None)
        if entry is None: raise ValueError(f"bad code {code} (nxt={nxt})")
        out += entry
        if prev is not None:
            dic[nxt] = prev + entry[:1]; nxt += 1
            if nxt == (1 << width) and width < MAXW: width += 1
        prev = entry
    return bytes(out)

RESET_AT = 1024              # emit CLEAR + reset dict when next_code reaches this

def encode(data):
    """Greedy LZW matching af.exe byte-exact: emit prefix code on miss, reset at RESET_AT,
    MSB-first packing, no trailing EOI."""
    dic = {bytes([i]): i for i in range(CLEAR)}; width = 9; nxt = FIRST
    bw = BitWriter(); w = b""
    for c in data:
        wc = w + bytes([c])
        if wc in dic:
            w = wc
            continue
        bw.write(dic[w], width)
        dic[wc] = nxt; nxt += 1
        if nxt == (1 << width) + 1 and width < MAXW: width += 1   # encoder bump (+1)
        if nxt >= RESET_AT:                                       # dict full -> CLEAR + reset
            bw.write(CLEAR, width)
            dic = {bytes([i]): i for i in range(CLEAR)}; width = 9; nxt = FIRST
        w = bytes([c])
    if w: bw.write(dic[w], width)                                # final code, no EOI
    return bw.flush()

if __name__ == "__main__":
    b = open(os.path.join(HERE, "cpld_native", "blinky.bin"), "rb").read()
    payload = b[HDR:]
    raw = decode(payload)
    print(f"decode: {len(payload)}B payload -> {len(raw)}B raw config")

    re_payload = encode(raw)
    full = b[:HDR] + re_payload
    print(f"encode: {len(raw)}B raw -> {len(re_payload)}B payload "
          f"(orig payload {len(payload)}B)")

    ok_payload = re_payload == payload
    ok_full = full == b
    print(f"\n  payload byte-exact: {ok_payload}")
    print(f"  full .bin byte-exact: {ok_full}")
    if not ok_payload:
        n = min(len(re_payload), len(payload))
        fd = next((i for i in range(n) if re_payload[i] != payload[i]), n)
        print(f"  first payload diff @ {fd} (len {len(re_payload)} vs {len(payload)})")
        print(f"    ours : {re_payload[max(0,fd-4):fd+8].hex(' ')}")
        print(f"    af.exe: {payload[max(0,fd-4):fd+8].hex(' ')}")
    sys.exit(0 if ok_full else 1)
