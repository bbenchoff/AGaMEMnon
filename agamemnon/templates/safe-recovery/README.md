# Safe recovery workspace

Start by diagnosing the host and making a complete read-only backup:

```text
agamemnon doctor
agamemnon backup backup/full-flash.bin --transport dap
```

Keep that image outside the build directory. SWD/DAP and the mask-ROM UART are
recovery transports. The flash-resident USB uploader is convenient but cannot
recover erased or corrupt main flash. The current L48 board needs the hardware
change documented in `docs/UART_BOOTLOADER.md` before Pico/UART recovery works.
