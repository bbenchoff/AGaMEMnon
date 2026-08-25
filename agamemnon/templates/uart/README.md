# FPGA UART

Transmits `0x55` at 115200 baud on qualified fabric output `PIN_16`.
Build and load it through DAP with `agamemnon build` and
`agamemnon run --transport dap`.

This is a soft-FPGA UART example on one exact output path. It is distinct from
the hard UART0/1/2 TX campaign routes and does not qualify UART receive,
arbitrary timing, another pin, or a modified placement.
