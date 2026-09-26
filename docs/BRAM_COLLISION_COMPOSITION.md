# Experimental Port-A collision composition

The experimental configuration emitter accepts the observed combination of
`PORTA_OUTREG` and `PORTA_WRITETHRU`, each 0 or 1, with `PORTB_WRITETHRU=1`,
at X13Y4 only. Both widths must be x18 (code 0), CLKMODE must be 01, both
ports' input/output clock fields must be enabled, reset fields must be zero,
and all other experimental fields must be zero. Existing single-field B4
admission is unchanged. Default emission still refuses this composition.

This exception permits **configuration encoding**, not general writable RAM,
route admission, clock qualification, or a supported inferred-memory policy.
The feature layer's initialized-read and writable-profile fences still apply.
Setting `AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG` also loads a separate experimental
primitive declaration during synthesis. It preserves the explicit B4 mode
parameters and exposes both address-stall inputs and the second async-reset
input. These are source declarations, not behavioral models or qualification
of active stall/reset behavior. The default primitive library is unchanged and
the extra declaration is not read with the option absent or empty. As with
other legacy registry flags, any nonempty value enables the option.
INIT encoding remains handled by the existing complete configuration surface;
arbitrary initialization behavior is not newly qualified.

Private workbench evidence from 2026-09-09 includes a vendor-source pair and
controlled image pairs differing only in the named mode cell and CRC. Eight
continuous-read silicon runs covered 6,208 transactions and 2,048 writes with
two repetitions per OUTREG/WRITETHRU combination. With OUTREG disabled, both
write-through settings produced new-data-compatible snapshots. With OUTREG
enabled, setting 0 produced an old-data-compatible trace and setting 1 a
new-data trace. Continuous reads did not distinguish old-data from no-change.

A later read-enable-controlled, three-cycle-read fixture distinguishes all
three hypothetical policies. Its four silicon runs completed 3,104
transactions and 1,024 writes: setting 0 produced the old-data trace, setting
1 the new-data trace, neither the no-change trace. This remains bounded to
eight addresses and one data lane, one routed clock net, continuous clock
enables, and the specific observer schedule. It is not a general timing model.

The evidence identifiers are `bram_read_during_write_silicon_20260909.json`
and `bram_collision_read_hold_20260909/session_r1/RESULT.json` in AG32-Docs.
Raw vendor artifacts remain in that workbench. No vendor binaries or routed
vendor netlists are required by this encoder exception.
