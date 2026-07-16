# AG32 flash-resident USB CDC uploader

Status as of 2026-07-16: the LQFP-48 USB CDC uploader is silicon-qualified for
enumeration, loader handshake, device identification, flash read, page erase,
flash write, full readback verification, restoration, and software reset. It
enumerates as `cafe:4001` on COM7 on the qualification bench and reports AG32
device ID `0x40200001`.

This is **not a mask-ROM USB bootloader** and it is **not USB DFU class**. AGM's
documented mask-ROM recovery path is UART0 with `BOOT0=1, BOOT1=0`. The USB
path described here is an ordinary program stored in main flash which exposes
the same AGM serial-loader command protocol over a TinyUSB CDC ACM port.
Erasing or corrupting this program requires SWD or UART0 ROM recovery.

## Can an untouched stock board upload over USB?

No. The stock **hardware** needs no modification, but the stock **firmware**
must be changed once.

The mask ROM does not provide USB boot. On the qualification board, the full
pre-write flash backup contained only 16 non-`0xff` bytes in sector 0, the
factory decompressor in sector 7, and the compressed fabric configuration in
sector 8. It did not contain this CDC uploader, and the target USB connector
did not enumerate as `cafe:4001` before installation.

Bootstrap the USB path once through either:

- DAP/SWD, as done in this qualification; or
- the UART0 mask ROM after wiring and asserting `BOOT0=1, BOOT1=0`.

After that one-time installation, the unmodified board hardware can receive
loader commands through the right-hand USB-C connector. DAP may remain
connected, but is no longer involved in USB transfers.

This qualification used the standalone loader at `0x80000000`; reset returns
to the loader. It proves that USB can identify, read, erase, write, verify, and
reset the chip. A product that should boot an uploaded application after reset
needs a resident-loader/application split and an entry mechanism. Do not use
the upstream example's default application address `0x80008000` on this board:
the qualified factory layout has decompressor data around `0x80007000` and a
compressed fabric image beginning at `0x80008100`. Select and link a
non-overlapping application region, preserve complete erase sectors, and keep
SWD or UART ROM available for recovery.

## What AGM documents

The AG32 reference manual documents a full-speed USB 2.0 controller and PHY.
For the LQFP-48 package, the USB data pair is on package pins 32 and 33. The
system boot-mode table documents normal flash boot and UART0 ROM boot; it does
not define a USB ROM-boot strap.

AGM's USB development note tells users to compile a TinyUSB example, program
it with the normal debugger flow, and then connect the board's USB connector.
The AG32VF303CCT6 board page also lists a USB interface. Those sources support
USB-capable application firmware, not a factory USB bootloader.

AGM's annotated board photo distinguishes the two USB-C connectors: the left
connector is labeled power-only and the right connector is labeled USB. The
right-hand connector is the target USB path qualified here. The yellow header
is the download/DAP connection.

## Upstream uploader used here

The firmware comes from the `examples/dfu` directory in os-q's
`platform-agm32` commit
[`71f4c316`](https://github.com/os-q/platform-agm32/tree/71f4c316c849c3e6b117b4830330360bbd61359b/examples/dfu).
Despite the directory name, its USB build is CDC ACM. Its descriptors advertise
VID:PID `cafe:4001`, manufacturer `AGM Uploader`, and product `UPLOADER CDC`.
The loader waits for byte `0x7f`, replies with AGM ACK `0x79`, and then accepts
the normal AGM loader commands over the virtual COM port.

The TinyUSB port is os-q `framework-agrv_tinyusb` commit
[`031adf2`](https://github.com/os-q/framework-agrv_tinyusb/tree/031adf292bdc967a6b5edd800f153b6480f5a4b0).
The tested PlatformIO packages were:

```text
platform-agm32          71f4c316c849c3e6b117b4830330360bbd61359b
framework-agrv_sdk      3c729cb
framework-agrv_tinyusb  031adf292bdc967a6b5edd800f153b6480f5a4b0
Agm32 Core              1.4.1
PlatformIO Core         6.1.18
```

## Required LQFP-48 build corrections

The upstream example is not usable unchanged on this board. The following
changes were required during bring-up:

1. Set the active project option `logic_device = AGRV2KL48`. The commonly
   shown `board_logic.device` spelling appears in PlatformIO's resolved
   configuration but this platform revision's builder reads the unprefixed
   `logic_device` option. Verify the verbose Supra invocation contains
   `set LOGIC_DEVICE {AGRV2KL48}`.
2. Run `logic_clean` before `buildlogic`, then use the generated compressed
   `.pio/logic/dfu_usb.inc` rather than the checked-in L100 `fpga_usb.inc`.
3. Exclude TinyUSB host sources for this device-only build:

   ```ini
   build_tinyusb_filter =
     -<src/host/>
     -<src/class/*/*_host.c>
     -<src/portable/ehci/>
     -<hw/mcu/agm/agrv2k_hcd.c>
   ```

4. In `agrv2k_dcd.c`, install `ENDPOINTLISTADDR` and initialize both EP0 queue
   heads before `USB_Run()`. The upstream `USB_InitDevice()` helper starts the
   controller first, creating an enumeration race. Do not report
   `DCD_EVENT_UNPLUGGED` on a bus reset or ordinary suspend.
5. In the bootloader's blocking CDC receive path, run `tud_task()` until
   `tud_mounted()` before calling `tud_cdc_n_read()`. Before configuration,
   the CDC driver's `ep_out` is zero. The unmodified loader consequently armed
   EP0 with its 2,048-byte CDC receive buffer and prevented the host from
   reading the device descriptor. Live dTD inspection showed EP0 pointing
   inside `_cdcd_itf` with `ExpectedBytes=2048`; after this fix EP0 remains a
   clean control endpoint.

The build used these definitions:

```ini
[env:usb]
extends = setup_usb
build_type = release
logic_device = AGRV2KL48
build_flags =
  -Os
  -DAGRV_FP_STACK=0
  -D DFU_FPGA_CONFIG=\"dfu_usb.inc\"
```

Reproducible build sequence:

```powershell
pio run -e usb -t logic_clean
pio run -e usb -t buildlogic -v
# Confirm: set LOGIC_DEVICE {AGRV2KL48}
pio run -e usb
```

The final bench image is 17,784 bytes with SHA-256
`33cc24a16545e6c09993046af597fe3a0cce1a9f3c66ffcbdc38b829358dc5d9`.
It embeds the compressed minimal USB fabric configuration and relocates the
loader into SRAM before waiting for CDC traffic.

## Persistent-write safety and bench transcript

Before the first write, the complete main flash and option bytes were saved:

```text
flash_before_usb.bin    262144 bytes
SHA-256 a1794c77902ef4b3b7adea7c438bcc1beaa95b445d71d23f311fd1620a579c62

options_before_usb.bin     128 bytes
SHA-256 6529f20e74a49cef5c1be43fde41e55030db0f7120d7f5139333238aec22bfa2
```

The uploader was written at `0x80000000`. It occupies flash sectors 0 through
4. The board's existing compressed fabric image begins at `0x80008100` in
sector 8 and was not erased or written. Each attempt ended with OpenOCD
`Verified OK` before reset.

Live post-reset observations from SWD:

```text
PC                   0x2000....       loader executing from SRAM
AHB clock enable     0x03000070 = 3  USB clock enabled
USB mode             0x410011a8 = 0x5002 (device)
USBCMD                0x41001140 = 1  controller running
ENDPOINTLISTADDR      0x41001158 = 0x20009000
PORTSC                0x41001184 = 0xe0000885 (connected and enabled)
EP0 OUT queue info    0x20009000 = 0x20408000
EP0 IN queue info     0x20009040 = 0x20400000
```

Before the CDC-read fix, EP0's dTD was active for 2,048 bytes at a buffer
inside the CDC interface object. Afterwards all EP0 dTD fields were zero while
waiting for a real setup request. This establishes that firmware reaches a
valid pre-enumeration state and that the target connector is electrically
seen by the controller.

Windows enumerated the board's separate DAP-Link interface as `cafe:1001` on
COM5, the Pico as `2e8a:000f` on COM6, and the target uploader as `cafe:4001`
on COM7. An earlier no-enumeration observation was caused by replugging the
left power-only connector instead of the right target-USB connector.

## Qualification results

All qualification steps passed on 2026-07-16:

1. Replugging the right target connector produced a USB composite device and
   CDC port with VID:PID `cafe:4001` on COM7.
2. `agrv32flash` completed the `0x7f` loader handshake and reported version
   `0x20`, option bytes `0x5a/0xa5`, device ID `0x40200001`, 128 KiB RAM, and
   256 KiB flash.
3. Reading `0x80000000..0x80004577` over USB produced 17,784 bytes. Its
   SHA-256 was
   `33cc24a16545e6c09993046af597fe3a0cce1a9f3c66ffcbdc38b829358dc5d9`,
   identical to the image written and verified earlier through SWD.
4. Flash sector 63 at `0x8003f000` was blank in the complete pre-test backup.
   A 232-byte deterministic marker with SHA-256
   `e868deb183de676f5dd26143a920d90232f375ab2db2ae77645996aa31f71b36`
   was erased/programmed through COM7. An independent 4-KiB USB readback
   matched all 232 marker bytes, and the other 3,864 bytes were all `0xff`.
5. Sector 63 was erased back to its original state. A second complete USB
   readback matched the saved pre-test sector byte-for-byte, was entirely
   `0xff`, and had SHA-256
   `f47a8ec3e9aff2318d896942282ad4fe37d6391c82914f54a5da8a37de1300c6`.
6. The loader RESET command completed. The target remained available as COM7,
   and a fresh handshake again returned device ID `0x40200001`.

AGaMEMnon now drives the CDC port directly:

```text
agamemnon probe --transport usb
agamemnon backup full.bin --transport usb
agamemnon flash app.bin --addr 0x80010000 --backup full.bin --transport usb
agamemnon go 0x80010000 --transport usb
```

The independent `agrv32flash` client remains a comparison oracle. The selected
COM-port baud is not meaningful for USB CDC transport.

## Hardware implications

No hardware change or USB-UART adapter is required on the qualified AGM board.
Use the right-hand target USB-C connector; the left connector is power-only.
A physical replug is the unambiguous way to make the host discover an uploader
newly installed through SWD. Once enumerated, the loader's software reset
returns to a working COM7 session. A custom production board may still benefit
from firmware/fabric control of the USB pull-up for an explicit timed detach.

Keep UART0 ROM or SWD recovery available. Unlike the UART ROM, this USB loader
depends on valid main flash, valid SRAM relocation, a working minimal fabric
configuration, clocks, TinyUSB, and the physical USB routing.

## Sources

- [AG32 reference manual, current AGM-hosted PDF](https://www.ag32mcu.com/wp-content/uploads/2026/02/AG32-MCU-Reference-Manual20250930%E4%BF%AE%E8%AE%A2%E7%89%88%EF%BC%89.pdf)
- [AGM USB development note](https://www.agmcn.com/doc/4193.html)
- [AG32 hardware-design considerations](https://www.ag32mcu.com/dev-docs/doc_ag32_hardware_design_considerations/)
- [AG32VF303CCT6 development-board page](https://www.ag32mcu.com/aum-product/products_board_ag32vf303cct6/)
- [os-q PlatformIO USB uploader source at the tested commit](https://github.com/os-q/platform-agm32/tree/71f4c316c849c3e6b117b4830330360bbd61359b/examples/dfu)
- [os-q AGM TinyUSB port at the tested commit](https://github.com/os-q/framework-agrv_tinyusb/tree/031adf292bdc967a6b5edd800f153b6480f5a4b0)
