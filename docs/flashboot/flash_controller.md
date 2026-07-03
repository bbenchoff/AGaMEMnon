# AG32 flash controller (`0x40001000`) — CONFIRMED, silicon-verified

The open flasher drives this controller directly (via generic `mww`/`load_image`), so **no vendor
`agrv` OpenOCD flash driver is needed**. The protocol below was reverse-engineered by *differential
capture* — tracing the vendor `agrv` driver's own register writes during a flash write (OpenOCD
`-d3`) — and then **verified on silicon**: erase → reads `0xFFFFFFFF`, program → reads back
byte-exact. Implemented in `agamemnon` (`agamemnon/program.py`) (`_fc_config` / `_fc_erase` / `_fc_program`, `flash` cmd).

## Registers (base `0x40001000`)

| off | name | role |
|---|---|---|
| `+0x04` | **KEYR** | unlock: write `0x45670123` then `0xCDEF89AB` (before every op group) |
| `+0x08` | **OPTKEYR** | unlock the option bytes (same two keys) — for the `0x81000000` config pointers |
| `+0x0C` | **SR** | status; **bit0 = BSY** (polls `0x21`→`0x20` while an op runs) |
| `+0x10` | **CR** | control (op select + start); `0x80` = lock/idle |
| `+0x14` | **AR** | address register (sector base for erase) |
| `+0x2C` | **CFG** | access config; set once to `0x8001045a` |

## CR operations (verified)

| write CR | meaning |
|---|---|
| `0x42` | sector erase + start (bit1 = SER, bit6 = STRT), with AR = sector base |
| `0x8211` | program-enable (PG mode) — then write data words to the flash address, controller programs them |
| `0x80` | lock/idle (write after each op) |

## The sequence (exactly what the open flasher does)

```
# config (once)
KEYR=KEY1; KEYR=KEY2
CFG(+0x2C)=0x8001045a ; AR(+0x14)=0x34 ; CR=0x4040 ; CR=0x80

# erase a 4 KB sector
KEYR=KEY1; KEYR=KEY2
AR(+0x14)=<sector_base> ; CR=0x42 ; CR=0x80
poll SR(+0x0C) bit0 until clear        # (the flasher uses a short sleep + a read-back verify)

# program a region
KEYR=KEY1; KEYR=KEY2
CR=0x8211
<write the data words to the flash address>   # generic memory write; controller programs them
CR=0x80
poll SR(+0x0C) bit0 until clear
```

Option-byte programming (to set the fabric config pointer at `0x81000030`/`0x81000038` for a
from-scratch flash-boot image) uses OPTKEYR + the same shape; that's the remaining `image` piece.

## Notes

- Verified end-to-end via `agamemnon flash <bin> --addr 0x80020000` on a scratch sector (backup first;
  erase→0xFF, program→byte-exact, then erased clean).
- The flasher polls with a short sleep and then **reads the region back and byte-compares** — the
  verify is the real safety, so a wrong timing can't pass silently. (An SR-BSY poll loop is a nice
  refinement; the sleep+verify is correct and proven.)
- Only vendor-adjacent piece left anywhere in the flow: the OpenOCD *binary* must be built with
  RISC-V-over-ADIv5-DAP (`riscv -dap`) — open, from `riscv-collab/riscv-openocd`.
