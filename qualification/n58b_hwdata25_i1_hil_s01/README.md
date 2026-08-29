# N5.8B HWDATA25 alternate-I1 HIL S01

This is a bounded silicon discriminator for the accepted N5.8A typed endpoint:
`HWDATA[25]` / `MCU_DIN69` / `X10Y5_MCU_DIN69`, rooted at
`X13Y9_BufMUX07` with mandatory first hop to `X13Y9_InputMUX06`.

The accepted HWDATA25 silicon composition terminated at ordinary LUT input I0.
This candidate retains the same endpoint, mandatory first hop, LUT site
`X14Y9_SLICE0`, output route, and L48 `PIN_18` observation surface, but changes
only the ordinary terminal to I1 (`X14Y9_IMUX01`) and uses `INIT=CCCC` as the
I1 identity function. The route-matched control keeps the same LUT placement
and output surface but emits constant zero. The retained SRAM-only firmware
repeatedly writes zero and bit 25 at the External-AHB window.

The experiment asks only whether this alternate I1 branch conducts. It does not
retest or broaden the accepted I0 claim, qualify adjacent lanes, arbitrary
placement/fanout, AHB protocol semantics, timing/Fmax, another package/device,
or device-wide nextpnr parity.

Two fresh output-directory builds with the frozen compiler, Yosys, nextpnr,
strict device database, source, PCF, and seed produced byte-identical candidate
and control images, compressed images, and canonical routed JSON. Both builds
closed with zero unmapped, predicted, or legacy-absolute selectors.

Desk verification:

```text
python qualification/n58b_hwdata25_i1_hil_s01/audit_package.py
python -m pytest -q qualification/n58b_hwdata25_i1_hil_s01/test_hil_s01.py
```

`package_manifest.json` deliberately does not authorize hardware. A separate
controller package, detached audit, and fresh short-lived one-use GO must bind
the frozen Git commit and all three exact SRAM payloads before board contact.
