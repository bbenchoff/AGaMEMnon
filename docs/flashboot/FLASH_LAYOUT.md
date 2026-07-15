# What we flash — the AG32 flash image, broken down

An AG32 program uses the shared **256 KB SPI flash** plus a separate **option-byte** region that tells the boot ROM where the fabric image lives. AGaMEMnon can write and verify main-flash regions. Option-byte programming is implemented only as the explicitly unverified `image --write-options` operation.

## The map

```
address range            what                         who writes it            who reads it
-----------------------  ---------------------------  -----------------------  -----------------------
0x80000000               MCU firmware (RISC-V, XIP)    agamemnon flash           the CPU (runs it)
0x80007000..0x800080ff*  [compressed only] decomp algo (vendor blob)           boot ROM (runs it)
<logic_addr>             Fabric bitstream             agamemnon flash           boot ROM (→ FCB → fabric)
...                      (rest of flash, free)
0x81000030 (2 words)     option: UNCOMPRESSED cfg ptr  unverified in AGaMEMnon   boot ROM (finds fabric)
0x81000038 (2 words)     option: COMPRESSED cfg ptr    factory-qualified layout boot ROM (finds fabric)
```
\* factory compressed layout; addresses are configurable.

Flash is 256 KB at `0x80000000`. The option bytes are a **separate region at `0x81000000`** (not main
flash), unlocked with OPTKEYR rather than KEYR.

## Part 1 — MCU firmware (`0x80000000`)

Plain RISC-V code, executed in place. The boot ROM branches here after configuring the fabric (when
BOOT0=0). This is your C/asm (built against `mcu/ag32.h`) with `riscv64-unknown-elf-gcc`, linked at
`0x80000000`. For a fabric-only design it can be a 16-byte idle stub (the factory board ships exactly
that — the fabric does the work); for a real node it's your application.

## Part 2 — Fabric bitstream (`<logic_addr>`)

The AGaMEMnon `.bin`. Two forms:

- **Uncompressed**: the raw 99,944-byte image written directly at `logic_addr`. The boot ROM can select it through the pointer at `0x81000030`. AGaMEMnon can write the main-flash image, but its option-pointer programming sequence is not silicon-qualified, so a new uncompressed self-boot layout is not a supported deployment path yet.
- **Compressed**: the LZW `.bin`; the boot ROM needs a **decompression-algorithm blob**
  (`LOGIC_ALGO_BIN`) sitting *before* it in flash, which it runs to inflate the image. That blob is a
  **vendor artifact**, so constructing this layout from an empty chip is not fully open. Replacing the image at the existing factory pointer while preserving that blob is silicon-qualified.

`logic_addr` is free to choose in flash as long as it doesn't collide with the MCU code; the factory
uses `0x80008100` (compressed, with its algo blob at `0x80007000`).

### What the bitstream bytes mean

An AGaMEMnon fabric `.bin` is an **8-byte header + payload**:

```
40 20 00 01   DEVICE_ID = 0x40200001   (checked against the live chip ID at config time)
00 00 ff ff   max config index = 0x0000ffff
<payload...>  the config data (raw, or LZW-compressed — see below)
```

- **Uncompressed** = header + the raw **99,936-byte** whole-fabric config image (99,944 B total). The
  last 4 bytes of the raw image are a **CRC-32/BZIP2** (poly `0x04C11DB7`, init/xor `0xFFFFFFFF`,
  big-endian) computed over `header(8) + raw[:99932]`. The FCB checks it at config time — a wrong CRC
  returns an `FCB STAT` error, so a corrupt image can't be silently loaded.
- **Compressed** = the same 8-byte header + a **variable-width LZW** codestream that inflates to that
  identical 99,936-byte raw image. Params: 8-bit literals, `CLEAR = 256`, initial code width **9
  bits**, **MSB-first** bit packing, dictionary **reset at 1024** entries. The bytes right after the
  header (e.g. `51 00 00 02 …`) are the first LZW codes, not fields. The boot ROM inflates this with
  the algo blob pointed to by option `0x81000040`; our open codec (`agamemnon pack`/`unpack`) encodes
  and decodes it **byte-for-byte** vs the vendor. Full bit-level detail: AGaMEMnon
  `docs/BITSTREAM_FORMAT.md`.

So "the compression bytes" are just: the fixed 8-byte device header, then an LZW stream (compressed)
or the raw config image (uncompressed) — with a CRC-32/BZIP2 guarding the decompressed result.

## Part 3 — Config / option bytes (`0x81000000`, 128 bytes)

A **separate region** (unlocked with OPTKEYR, not KEYR). It holds the chip's boot/config *policy* and
the *pointers* that tell the boot ROM where the fabric bitstream is. Every field is stored as a value
plus its bitwise complement — self-validating; blank = `0xFFFFFFFF`. This is the **factory** layout,
read back live (`agrv options_read` + a raw dump of the region):

| offset | field | factory value | what it does |
|---|---|---|---|
| `0x81000000` | option / RDP byte | `ffff5aa5` | **read-protection level** (`0xA5` = off) + user config bits, decoded as `option byte register = 0x03fffffd` — includes **stop-mode** and **standby-mode** "no reset on entry" |
| `0x81000004`–`1f` | write-protection | `ffffffff…` | per-sector **write-protect** bitmap (all-ones = nothing protected) |
| `0x81000020` | osc config + user data | `a857ffff` | **oscillator trim** `0x57` (+ complement `0xA8`); **user data** `0xFFFF` (free for your use) |
| **`0x81000030`** | **uncompressed FPGA cfg ptr** | *(blank)* | `(addr, ~addr)` — if set, boot ROM loads the fabric **uncompressed** from `addr` |
| **`0x81000038`** | **compressed FPGA cfg ptr** | `80008100` / `7fff7eff` | `(addr, ~addr)` — if set, boot ROM loads the fabric **compressed** from `addr` |
| **`0x81000040`** | **decompressor-algo addr** | `80007000` / `7fff8fff` | `(addr, ~addr)` — the RISC-V blob the boot ROM runs to inflate a compressed config |

**How the boot ROM chooses:** it checks `0x81000030` first — a valid `(addr,~addr)` there means
**uncompressed**, load from `addr`. Otherwise it reads `0x81000038` (**compressed**), runs the algo
at `0x81000040`, inflates, and loads. That's exactly the factory state above: compressed config at
`0x80008100`, algo at `0x80007000`. **Encryption** (unused here — everything ships "non-encrypted")
would zero these pointer slots and carry the address encrypted elsewhere.

The intended uncompressed layout sets `0x81000030 = (logic_addr, ~logic_addr)`. `agamemnon image` writes MCU and fabric main-flash regions with `--flash`; it writes this option field only when `--write-options` is supplied. That option-byte operation is explicitly unverified and requires a backup.

## The boot sequence (how it all comes together)

1. Power-on → the mask **boot ROM** at `0x00010000` runs.
2. It reads the option bytes at `0x81000000` → gets the fabric `logic_addr` + compressed flag.
3. It reads the fabric bitstream from flash, LZW-decompresses if compressed (running the algo blob),
   and streams it into the **FCB** → the fabric is configured.
4. It branches on **BOOT0**: `=0` → jump to MCU firmware at `0x80000000`; `=1` → the UART serial
   bootloader (recovery / in-system programming).
5. Your firmware runs against an already-configured fabric.

**Fabric config only happens at a real power-on reset** — a debugger warm reset (nSRST) does *not*
re-trigger it.

## What `agamemnon image` writes

Given `--mcu firmware.bin` + `--fabric fabric_uncomp.bin` + optional `--logic-addr`:

```
0x80000000  ← firmware.bin
logic_addr  ← fabric_uncomp.bin          (default logic_addr chosen clear of the firmware)
0x81000030  ← (logic_addr, ~logic_addr)  only with --write-options (unverified)
```

With `--flash`, the MCU and fabric regions use the silicon-qualified open flasher (`0x40001000` controller, no vendor flash driver). Without a matching existing pointer, those main-flash writes do not make the new fabric region bootable. The option-pointer write requires `--write-options`, is not silicon-qualified, and must not be described as a supported self-boot path.

## Recovery

Always `agamemnon backup full.bin` first. Restore the backup over SWD if a main-flash write is bad. BOOT0=1 selects the mask-ROM UART recovery path, but AGaMEMnon does not implement that serial protocol. The SWD debug transport is independent of main-flash contents.
