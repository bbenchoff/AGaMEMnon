# AG32 flash controller

AGaMEMnon programs main flash through the controller at `0x40001000`. The
implementation uses generic OpenOCD memory operations and does not require the
vendor `agrv` flash driver.

## Registers

| Offset | Name | Function |
|---|---|---|
| `0x04` | `KEYR` | main-flash unlock; write `0x45670123`, then `0xcdef89ab` |
| `0x08` | `OPTKEYR` | option-byte unlock using the same key pair |
| `0x0c` | `SR` | status; bit 0 is busy |
| `0x10` | `CR` | operation control and start |
| `0x14` | `AR` | sector address for erase |
| `0x2c` | `CFG` | access configuration; AGaMEMnon writes `0x8001045a` |

## Control values

| `CR` value | Operation |
|---|---|
| `0x42` | sector erase and start, using `AR` |
| `0x8211` | enable programming; memory writes program flash |
| `0x80` | lock/idle |

## Main-flash sequence

```text
initialization:
  KEYR = 0x45670123
  KEYR = 0xcdef89ab
  CFG  = 0x8001045a
  AR   = 0x34
  CR   = 0x4040
  CR   = 0x80

erase one 4-KiB sector:
  unlock KEYR
  AR = sector_base
  CR = 0x42
  CR = 0x80
  wait, then verify erased bytes

program:
  unlock KEYR
  CR = 0x8211
  write data words to the target flash address
  CR = 0x80
  wait, then read back and compare
```

`agamemnon/program.py` uses a bounded delay followed by byte-for-byte readback
verification. It does not use `SR.BSY` as its completion loop.

Main-flash backup, erase, programming, and readback comparison are supported.
Option-byte programming uses `OPTKEYR` and is exposed only by the unsupported
`image --write-options` operation.

The probe transport requires an OpenOCD binary with AGM's
`target create riscv -dap` extension. The packaged target configuration and
flash-controller implementation are open; stock upstream OpenOCD does not
provide that target option.
