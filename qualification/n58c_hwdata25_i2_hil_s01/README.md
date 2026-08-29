# N5.8C HWDATA25 graph-legal-I2 HIL S01

This is a bounded silicon discriminator for the accepted N5.8A typed endpoint:
`HWDATA[25]` / `MCU_DIN69` / `X10Y5_MCU_DIN69`, rooted at
`X13Y9_BufMUX07` with mandatory first hop to `X13Y9_InputMUX06`.

The accepted I0 and I1 silicon compositions terminate at `X14Y9_SLICE0`.
The exact fixed-site I2 candidate and a raw-graph-reachable off-corridor I2
candidate were both rejected fail-closed before image emission; their immutable
records are retained beside this package. This active child makes the smallest
one-tile move that satisfies the typed Y9 entry corridor and has directed input
and output closure: `X15Y9_SLICE2.I2` / `X15Y9_IMUX10`, with `INIT=F0F0` as
the I2 identity function.

The endpoint and mandatory first hop remain unchanged. The output path starts
at `X15Y9_OMUX08`, rejoins the previously accepted path at `X14Y9_RMUX15`,
and terminates at the same L48 `PIN_18` / Pico GP8 observation surface. The
route-matched control keeps the same LUT placement and exact output route but
emits constant zero. The retained SRAM-only firmware repeatedly writes zero and
bit 25 at the External-AHB window.

The experiment asks only whether this exact graph-legal I2 composition
conducts. It does not qualify the rejected same-site I2 branch, arbitrary
placement or fanout, adjacent lanes, AHB protocol semantics, timing/Fmax,
another package/device, or device-wide nextpnr parity.

Two fresh output-directory builds with the frozen compiler, Yosys, nextpnr,
strict device database, source, PCF, and deterministic routing policy produced
byte-identical candidate and control images, compressed images, and routed
JSON. Both builds closed with zero unmapped, predicted, or legacy-absolute
selectors. The tracked routed JSON is canonicalized for fresh-checkout audits.

Desk verification:

```text
python qualification/n58c_hwdata25_i2_hil_s01/audit_package.py
python -m pytest -q qualification/n58c_hwdata25_i2_hil_s01/test_hil_s01.py
```

`package_manifest.json` deliberately does not authorize hardware. A separate
controller package, detached audit, and fresh short-lived one-use GO must bind
the frozen Git commit and all three exact SRAM payloads before board contact.
