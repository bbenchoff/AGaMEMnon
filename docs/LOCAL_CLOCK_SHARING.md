# Local clock sharing: implementation and qualification boundary

Native-enable tile sharing needs both control-line selection and a clock feed
for every selected local line. Selecting line 1 on a register is insufficient
when the tile still emits only the line-0 clock feed.

The experimental emitter now supplies the second tile-clock selector and seam
for validated line-1 consumers. It derives physical fields from the shipped
configuration template and checks the active per-slice clock leaves. The
current implementation admits this composition only for the MCU bus clock
profile; it does not establish support for other clock profiles or rates.

Two compositions are being qualified:

- `AGRV2K_DUAL_NATIVE_CONTROL=1`: two independent native-enable groups use the
  two local clock lines. Ordinary registered state cannot share that tile.
- `AGRV2K_MIXED_NATIVE_CONTROL=1`: one native-enable group uses one line and
  ordinary registered state uses the other, idle line. Both occupied lines,
  including two roots carrying the same enable net, leave no idle line.

The options remain experimental and default off. Placement must preserve
native-group membership, register/input legality, fixed endpoints and all
other existing checks. Emission independently rejects an ordinary register
assigned to a driven enable line. Ordinary register input-mode bits are
preserved when its local clock selection changes.

A fresh ordinary-source dual-enable build from commit `62c254d` reproduces
the diagnostic image that passed the independent-enable contract three times.
The mixed composition also passed its diagnostic contract after clock-line
isolation, but its fresh placement implementation is still under validation.
These bounded results do not qualify arbitrary enable compositions, establish
physical speed, or repair the outstanding compact addsub16/util20 failures.

Retained-image regression, fresh-source qualification and placement boundary
tests must complete before changing supported defaults. Private vendor and
silicon evidence remains in AG32-Docs under
`tools/vendor_parity/routing_aware_packing_20260908/`.
