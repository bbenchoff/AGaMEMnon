# USB CDC uploader project

USB is a hard MCU controller/PHY, so this template uses the pinned external AGM
PlatformIO and TinyUSB frameworks. Before `agamemnon build`, reproduce the
qualified patches from the AGaMEMnon
[USB uploader example](https://github.com/bbenchoff/AGaMEMnon/blob/main/examples/usb_cdc_uploader/README.md).
The external AGM SDK does not contain a top-level license file; review its
provenance before use or redistribution.

An untouched board cannot boot this over USB. Install it once through DAP or
mask-ROM UART, then use first-class AGaMEMnon USB commands:

```text
agamemnon probe --transport usb
agamemnon backup full.bin --transport usb
agamemnon flash app.bin --addr 0x80010000 --backup full.bin --transport usb
agamemnon go 0x80010000 --transport usb
```
