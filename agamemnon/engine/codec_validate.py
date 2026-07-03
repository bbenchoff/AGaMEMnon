#!/usr/bin/env python3
"""Validate the recovered AGM 'AsciiEncrypt' arch-DB codec against real *_cfg.csv files.

Reimplements af.exe FUN_140501dc0 (constructor) + FUN_1404f7830 (transform) from the
extracted static blobs (perms.bin, seed.bin). Read-only on the package files.
"""
import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "ghidra_out", "codec_data")
# Directory of vendor arch-DB `*_cfg.csv` files, used ONLY by the optional self-test below (never at
# build/flash time). Point $AGAMEMNON_ARCH_CFG at your own tool-agrv install to run it, e.g.
# .../tool-agrv_logic/etc/arch/rodinia/config
CFG  = os.environ.get("AGAMEMNON_ARCH_CFG", "")

# 96-char substitution alphabet (verbatim from FUN_140501dc0)
ALPHA = ("0123456789"
         "abcdefghijklmnopqrstuvwxyz"
         "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
         "!\"#$%&'()*+,-./"
         ":;<=>?@"
         "[\\]^_`"
         "{|}~"
         " "
         "\t").encode("latin1")
assert len(ALPHA) == 96, len(ALPHA)

TRIG = set(b"ezEZ\n")     # trigger chars at state+0xc820
N = 100

def build_banks():
    seed  = open(os.path.join(DATA, "seed.bin"), "rb").read()
    perms = open(os.path.join(DATA, "perms.bin"), "rb").read()
    assert len(seed) == 256 and len(perms) == N * 96
    dec = [bytearray(seed) for _ in range(N)]
    enc = [bytearray(seed) for _ in range(N)]
    for t in range(N):
        p = perms[t*96:(t+1)*96]
        for j in range(96):
            a = ALPHA[j]; b = p[j]
            dec[t][a] = b      # decode: alphabet-char -> perm-char
            enc[t][b] = a      # encode: perm-char    -> alphabet-char
    return dec, enc

def nextidx(c):
    return (((c*0x71 + 0x4f) % 13) * 0x2f + 0x35) % N

# Direction confirmed empirically (2026-06-29): af.exe READS the encoded arch files with
# transform MODE 8 (encode bank, trigger on OUTPUT) -> that is the real DECODE to plaintext.
# MODE 4 (decode bank, trigger on INPUT) is the real ENCODE (plaintext -> obfuscated).
def decode(data, banks, init=1):        # MODE 8 -> plaintext CSV
    A, B = banks
    table = 0; counter = init; out = bytearray()
    for x in data:
        y = B[table][x]; out.append(y)
        if y in TRIG:
            c = counter; counter += 1; table = nextidx(c)
    return bytes(out)

def encode(data, banks, init=1):        # MODE 4 -> obfuscated form
    A, B = banks
    table = 0; counter = init; out = bytearray()
    for x in data:
        out.append(A[table][x])
        if x in TRIG:
            c = counter; counter += 1; table = nextidx(c)
    return bytes(out)

import re
def tokens(buf):
    # longest [A-Za-z_][A-Za-z0-9_]{4,} identifier-like runs
    return sorted(set(re.findall(rb"[A-Za-z_][A-Za-z0-9_]{4,}", buf)), key=len, reverse=True)

def main():
    if not CFG:
        print("self-test skipped: set $AGAMEMNON_ARCH_CFG to a vendor "
              "tool-agrv .../etc/arch/rodinia/config dir (with *_cfg.csv) to run it.")
        return
    banks = build_banks()
    files = sorted(glob.glob(os.path.join(CFG, "*_cfg.csv")))
    files = [f for f in files if os.path.getsize(f) > 0]
    print("alphabet ok (96), seed identity, N=%d, triggers=%r, files=%d" % (N, bytes(TRIG), len(files)))
    ok = bad = readable = 0
    for path in files:
        name = os.path.basename(path)
        E = open(path, "rb").read()
        P = decode(E, banks, 1)              # MODE 8 -> plaintext
        if encode(P, banks, 1) != E:         # MODE 4 round-trips back to the file
            print("  FAIL %-32s round-trip mismatch" % name); bad += 1; continue
        ok += 1
        if P[:8] in (b"netlist,", b"config_i") or P.startswith(b"config"):
            readable += 1
    print("RESULT: %d/%d round-trip MATCH, %d failed; %d/%d decode to a recognized CSV header"
          % (ok, ok+bad, bad, readable, ok))

if __name__ == "__main__":
    main()
