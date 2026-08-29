# N5.8A HWDATA25 HIL S01

This is a bounded silicon discriminator for the exact N5.8A typed endpoint:
`HWDATA[25]` / `MCU_DIN69` / `X10Y5_MCU_DIN69`, rooted at
`X13Y9_BufMUX07` with mandatory first hop to `X13Y9_InputMUX06`.

The candidate feeds one fixed ordinary LUT at `X14Y9_SLICE0`; the LUT drives
the retained L48 `PIN_18` observation surface. The route-matched control keeps
the same LUT placement and output surface but emits constant zero. SRAM-only
firmware repeatedly writes zero and bit 25 at the External-AHB window so the
candidate should produce two high/low epoch widths while both bracketing
controls remain low.

The experiment does not qualify adjacent lanes, arbitrary endpoint placement,
AHB protocol semantics, fabric readback, timing/Fmax, another package/device,
or device-wide nextpnr parity.

Desk verification:

```text
python qualification/n58_hwdata25_hil_s01/audit_package.py
python -m pytest -q qualification/n58_hwdata25_hil_s01/test_hil_s01.py
```

`package_manifest.json` deliberately does not authorize hardware. A separate
controller package, detached audit, and fresh short-lived one-use GO must bind
the frozen Git commit and all three exact SRAM payloads before board contact.
