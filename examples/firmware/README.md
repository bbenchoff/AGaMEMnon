# GPIO loopback — logic-function verification on silicon

Proves the AG32 fabric *computes* and the result is observable from the MCU, end to end.

**Design** (`loop.ve` + `loop_macro.v`): an inverter wired between two MCU GPIO bits via the
`alta_mcu` hard block —
```
GPIO4_1 din:OUTPUT      # MCU drives  -> macro input  din_out_data (+ din_out_en)
GPIO4_2 dout:INPUT      # MCU reads   <- macro output dout_in
assign dout_in = ~din_out_data;
```
Built once with the AGM headless flow (`tools/loopback/build_cpld.ps1`) as a reference bitstream
(`loop.bin`, 99,944-byte uncompressed config). The GPIO↔fabric-node binding is in its `route.tx`
(`gpio4_io_out_data[1]` → … → `alta_rv3200`, the RISC-V core node).

**Test** (`looptest.c`): a freestanding RISC-V stub loaded to SRAM via OpenOCD. It enables the FCB +
GPIO4 clocks, configures the fabric from `loop.bin` (`FCB_AutoConfig`), sets GPIO4.1 output / GPIO4.2
input, then drives din and reads dout. Results stored at `0x20001000`.

**Result on real silicon (2026-06-30):**
```
STAT        = 0x000f0002   fabric ACTIVE, 0 errors
din=0 -> dout=1  (GPIO4.2=0x4)
din=1 -> dout=0  (GPIO4.2=0x0)
```
dout = NOT din, both polarities → the fabric LUT computes and the MCU observes it.

## Run
```
# 1. build the reference (once, vendor headless flow): tools/loopback/build_cpld.ps1 -Name loop
# 2. compile looptest.c (riscv64-unknown-elf-gcc, -Ttext=0x20000000, see pnr build notes)
# 3. via OpenOCD: load loop.bin@0x20002000, looptest.bin@0x20000000, set pc/sp, resume, read 0x20001000..c
```
Registers: GPIO4 @ 0x40018000 (DIR +0x400, AFSEL +0x420, DATA[mask] at base+(mask<<2));
APB clock enable @ 0x03000060 (FCB=bit0, GPIO4=bit8); FCB @ 0x40010000 (CTRL/AUTO/STAT).

## Next (open-toolchain closure)
Model `alta_mcu` as a bel in `nextpnr-agrv` (GPIO_O→RogicTILE/UFMTILE OMUX, GPIO_I←RMUX; binding
from `route.tx`), rebuild this loopback through the open flow + bitgen+CRC, and re-run this test.
