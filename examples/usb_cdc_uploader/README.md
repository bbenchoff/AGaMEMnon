# AG32 LQFP-48 USB CDC uploader patches

These patches reproduce the firmware described in
[`docs/USB_CDC_UPLOADER.md`](../../docs/USB_CDC_UPLOADER.md) from the tested
upstream revisions. They are kept as patches because the complete uploader and
TinyUSB sources belong to their upstream repositories.

```powershell
git clone https://github.com/os-q/platform-agm32.git
git -C platform-agm32 checkout 71f4c316c849c3e6b117b4830330360bbd61359b

git clone https://github.com/os-q/framework-agrv_tinyusb.git
git -C framework-agrv_tinyusb checkout 031adf292bdc967a6b5edd800f153b6480f5a4b0

git -C platform-agm32 apply ../AGaMEMnon/examples/usb_cdc_uploader/platform-agm32.patch
git -C framework-agrv_tinyusb apply ../AGaMEMnon/examples/usb_cdc_uploader/framework-agrv-tinyusb.patch
```

PlatformIO normally owns the installed copies under `.platformio`. Apply the
same changes there, run `logic_clean`, run `buildlogic -v`, and verify that the
actual Supra command contains `set LOGIC_DEVICE {AGRV2KL48}` before building
or flashing anything. After `buildlogic`, change the USB environment's
`DFU_FPGA_CONFIG` from the checked-in `fpga_usb.inc` to the generated
`dfu_usb.inc`; that generated-artifact selection is deliberately called out
separately because the exact `.ini` context varies between package releases.

The patches do not add a USB recovery ROM. They repair and specialize the
upstream flash-resident CDC uploader for this L48 bring-up.
