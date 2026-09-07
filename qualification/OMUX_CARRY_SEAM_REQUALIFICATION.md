# Exact combinational carry seam, 2026-09-04

The previously inconclusive retained probe now passes three silicon runs with
the corrected owner-based OMUX emission. Normal CLI packing emits image
`a85fbd2619fba032e791d252a66cd3b6af95083e77bc8757b972fad422e68fc8`.
The exact routed artifact remains
`42c0323c6131ebeae7911a2294f9e129e9077e98d1db5e434d42b13feadf2c05`.

An independent topology check binds the COUT/CIN-connected physical chain:
seed X10Y4_SLICE14 -> X10Y4_SLICE15 -> X10Y3_SLICE0, all combinational.
The crossing is the actual downward slice15-to-slice0 seam, not a freshly
routed alternative or a software result substituted for fabric output.

Original MCU control passes. The input/output control re-emits byte-identically
as `18727f90...` and verifies GP2/PIN_15 input -> GP6/PIN_16 output for0,1,1,0.
Each of three carry loads then follows that same input sequence. Physical
output samples are respectively0/1000,1000/1000,1000/1000,0/1000 high. AHB low2
bits are1,2,2,1, proving both the upstream sum and downstream carry result.
Raw reads arefffffffd/fffffffe; upper lanes are unqualified, not masked into
a claimed full-width bus result. Every activation reports FCB000f0002 and a
fresh loader completion sentinel.

The normal emitter differs from the old pinned image only at the five
previously audited CFG_OMUX selector clears and integrity bytes. This new
positive result supersedes the old *inconclusive* diagnosis for this exact
image/chain; it does not assert that every carry seam, chain length, package,
or sequential timing path is qualified.

Final board reset and lock release succeeded, Pico pins returned to inputs,
zero flash writes and no Pico reflash. Evidence in AG32-Docs:
`tools/vendor_parity/gpt6_carry_seam_silicon_20260904`, including full Pico
transcript, FCB/AHB logs, staged images and independent ANALYSIS.json.

All16 images changed by the OMUX correction now have explicit fresh silicon
dispositions, including causal controls. Next is coordinated manifest/SDK/
clock/fingerprint pin migration and complete regression validation. Those
pins and public main have not been changed by this qualification step.
