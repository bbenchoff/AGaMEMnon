# AG32 flash and boot layout

The AG32 uses 256 KiB of main flash plus a separate option-byte region that
contains boot policy and fabric-image pointers.

## Address map

```text
0x80000000..0x8003ffff  main flash
0x80000000              MCU firmware/reset vector
0x80007000              qualified-board compressed-image decompressor
0x80008100              qualified-board compressed fabric image
0x81000000              option bytes (separate controller region)
```

The decompressor and image addresses are option-controlled; the values above
describe the qualified board layout.

## Fabric image forms

An uncompressed fabric image is:

```text
8-byte device header + 99,936-byte raw configuration = 99,944 bytes
```

The option pair at `0x81000030` selects an uncompressed image. AGaMEMnon can
write the main-flash data but does not support option-byte programming as a
deployment path.

A compressed image uses the same header followed by the AGRV2K LZW stream.
The option pairs at `0x81000038` and `0x81000040` select the image and the
decompressor. The supported persistent workflow replaces the image at the
existing pointer and preserves the decompressor.

Full image details are in [../BITSTREAM_FORMAT.md](../BITSTREAM_FORMAT.md).

## Option-byte fields

Pointers are stored as `(value, bitwise-complement)` pairs. Blank words are
`0xffffffff`.

| Address | Qualified-board value | Purpose |
|---|---|---|
| `0x81000000` | `ffff5aa5` | read-protection and user option bits |
| `0x81000004..0x8100001f` | all ones | main-flash write-protection bitmap |
| `0x81000020` | `a857ffff` | oscillator trim and user data |
| `0x81000030` | blank | uncompressed fabric pointer |
| `0x81000038` | `80008100`, `7fff7eff` | compressed fabric pointer |
| `0x81000040` | `80007000`, `7fff8fff` | decompressor pointer |

The boot ROM selects a valid uncompressed pointer first. Otherwise it uses the
compressed pointer and decompressor pointer.

## Boot sequence

1. The mask ROM reads option bytes.
2. It selects the fabric image and decompressor mode.
3. It obtains the 99,936-byte raw configuration and streams it into the FCB.
4. With BOOT0 low, it branches to MCU firmware at `0x80000000`; with BOOT0
   high, it enters the mask-ROM UART bootloader.

Fabric flash configuration occurs at power-on, not on an ordinary debugger
warm reset.

## Supported writes

```bash
# Required before any persistent change
agamemnon backup full-flash.bin

# Replace the compressed fabric image selected by the existing pointer
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

`agamemnon image --flash` can write MCU and uncompressed fabric data to main
flash, but those writes are bootable only if the board already points to that
location. `image --write-options` exposes an unsupported option-byte operation
and is not part of the qualified boot workflow.

Main-flash erase granularity is 4 KiB. Preserve every complete affected sector,
especially a sector shared by the decompressor and compressed image.

## Recovery

Restore a complete backup over SWD:

```bash
agamemnon flash full-flash.bin --addr 0x80000000
```

The SWD path does not depend on valid main-flash contents. AGaMEMnon does not
implement the BOOT0 UART recovery protocol.
