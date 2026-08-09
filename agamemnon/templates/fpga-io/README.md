# FPGA combinational I/O

This release-safe source-build example drives PIN25..PIN28 respectively
high, low, high, low through
four preserved LUTs to the qualified onboard LED outputs (`PIN_25` through
`PIN_28`). It exercises synthesis, placement, routing, bit generation, and all
four physical output corridors without relying on unqualified generic state.

```text
agamemnon build
agamemnon run --transport dap
```

`run` loads both images into SRAM and does not touch flash.
