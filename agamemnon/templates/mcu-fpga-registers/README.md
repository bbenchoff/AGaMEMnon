# MCU/FPGA registers

This volatile example configures the fabric and samples its counter through
External AHB at `0x60000000`.

```text
agamemnon build
agamemnon run --transport dap --words 4
```
