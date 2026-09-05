# BRAM-only clock activation

The clock emitter previously selected a generated clock profile only when the
validated tree contained active slice clock leaves. A design with only a BRAM
clock consumer consequently emitted the idle profile, even though its BRAM
clock routing validated successfully.

Source activation now includes validated BRAM clock edges. It still derives
authority from the routed validator, not cell names or mere BRAM placement.
Clock ratios, source catalog, strict closure, and initialized-memory admission
are unchanged. The existing explicit no-generation behavior is preserved;
strict clock validation continues to reject that option for active consumers.

## Tests

The initial regression matrix reproduced two BRAM-only activation failures
(10 MHz and 20 MHz); its fourteen slice/mixed/idle/disabled controls passed.
The extended matrix covers HSE PLL at both frequencies and the default MCU-bus
source, each with BRAM-only, slice-only, mixed, idle, and disabled conditions.
It checks generated preamble bytes, HSE input enable, writable-bit ownership,
and the validator's rejection of disabled generation for active consumers.
Clock-resource and feature-protocol suites: **94 passed**.
Preamble, ownership, BRAM admission, TMUX9 and retained-image replay suites:
**103 passed, 2 skipped**, including all 58 retained byte-identity artifacts.
The two skips require native nextpnr/Yosys unavailable to the Windows test
process; this does not qualify a rebuilt native placement implementation.

## Hardware evidence boundary

A research experiment on L48 used an experimental shared-ground route and
explicit original INIT restoration. Enabling the open generated 20/8 MHz clock
profile and HSE input produced three complete original parity-oracle passes.
The unchanged idle-clock image was previously negative. A separate all-ones
read changed from zero to all ones with the clock intervention.

That experiment does not qualify the full source-build flow, general BRAM
widths or ports, or removal of initialized-memory admission fences. In
particular, it used a 20 MHz intervention; the ordinary default MCU-bus setting
remains 10 MHz. A separate follow-up using the repaired ordinary emitter at
that default setting also passes the complete original oracle three times;
the idle baseline fails three times, with all controls passing. This follow-up
still uses research-only INIT restoration and experimental placement, so it
does not remove the source-build qualification boundary. No vendor material
is required by this implementation or its regression tests.
