# SERV OMUX-owner requalification, 2026-09-04

The corrected retained signature-19 and repeated-JAL heartbeat images each
pass three reset-gated silicon runs on L48. Every run observes PIN_25/Pico GP12
low for2000 samples with reset asserted, then the expected signature/heartbeat
after release, then low for2000 samples after reassertion. Reset is PIN_10/GP4,
per the recovered electrical map; an older research script incorrectly used
GP0 and was not used unchanged.

Signature image SHA256:
`f4d4d7d85e06726350a75782e21e4fa0f67c4f7bec0f2d3681590bc483f2c30d`.
Every released run is12000/12000 high at1us and6000/6000 high at7us.

Heartbeat image SHA256:
`ba6f661ee888a56a54ed073be6b735b40b3762cf011bb7b5b77d373aa92222a4`.
Released high counts at1us:6018,6003,6006 of12000; at7us:3007,3006,2997 of6000.
Separate12000-sample edge counts:1295,1293,1294. Both levels are observed at
both intervals; the edge capture confirms ongoing transitions after release.

Before candidates, the original public32 MCU control passes. A freshly rebuilt
normal SDK SERV-blinky control reproduces exact hash `fe7ecca2...` and passes
the GP4/GP12 reset-gated sequence (1499 high/1501 low in3000 released samples).
All image activations report FCB=000f0002 and fresh loader sentinel. The Pico
protocol is checked by PING and CAP8 usage response; no reflash is performed.
Final cleanup returns Pico pins to inputs, resets the board, and releases the
lock. No flash writes.

Manifest environments are retained exactly: HSE8,SYSCLK25,LEFT_PAD_OUT1,
DIRECT_D1. This is focused seven-form RV32I signature/JAL qualification of
these exact routed artifacts, not full ISA compliance, arbitrary designs,
timing closure, or every BRAM mode. Earlier positive hardware and inherited
offline replay records remain historical; these are fresh changed-byte tests.

Evidence in AG32-Docs: `tools/vendor_parity/gpt6_serv_omux_silicon_20260904`,
including images, fresh loader, raw FCB logs, Pico transcript and independent
ANALYSIS.json. Thirteen prior changed-image dispositions plus these two leave
only carry-seam unresolved in the16-image OMUX migration. No public pins or
main promotion in this step.
