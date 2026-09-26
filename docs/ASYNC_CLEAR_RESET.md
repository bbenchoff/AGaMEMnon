# Asynchronous clear

Ordinary `build --uarch` supports positive-edge registers with an active-high
asynchronous clear to zero. Clock enable is preserved as data-input hold logic:

```verilog
always @(posedge clock or posedge reset)
    if (reset) count <= 0;
    else if (enable) count <= count + 1'b1;
```

The physical implementation uses one admitted asynchronous-clear line per
LogicTile, with a witnessed feeder into CtrlMUX0. The packer keeps incompatible
control groups separate and refuses a composition it cannot implement.
`--no-async-clear-reset` disables this support and restores the earlier refusal.

The reset correction preserves local register feedback through input permutation
and fanout splitting. The clock emitter also clears the external-reset polarity
field on tiles using asynchronous clear; leaving its ordinary idle value set
reverses reset behavior.

## Hardware evidence

On L48 at 10 MHz, fresh source builds of `clk_rst_high.v` and
`clk_rst_low.v` pass held-reset and resumed-counter checks after these fixes.
The high example measured 1220/1220/1221 rising edges per second; the low example
measured 1221/1220/1221, against 1220.7 expected. A separate asynchronous-clear
counter with an enable asserted every other clock measured 1221/1221/1220.
Reset held all three outputs static at zero. Positive controls and final board
cleanup passed. Exact image and source bindings are recorded in
[the qualification ledger](../qualification/async_clear_reset_evidence.jsonl).

The low example defines `reset_n = ~reset` internally, then uses
`negedge reset_n`. Its external reset pin is still active high, and synthesis
normalizes it to the same admitted register class. It is not evidence for a
separate native active-low reset implementation.

These measurements apply to the recorded builds. Release integration and
additional placement seeds are checked separately. Asynchronous preset,
nonzero reset values, negative-edge clocks, mixed independent clear groups,
and reset timing margins are not qualified by these counter measurements.
The multi-tile example remains a qualification vehicle until its board result
is recorded.

## Example

```sh
agamemnon build examples/async-clear-reset/clk_rst_high.v --uarch \
  --pcf examples/async-clear-reset/clock.pcf --freq 10 \
  --write-routed async-counter.routed.json -o async-counter.bin
```

The enabled counter example uses the same PCF. Verification covers reset
assertion between clock edges, enabled updates, disabled holds, reset priority,
and both enable polarities at the RTL-lowering boundary. Those simulation
checks supplement the hardware evidence; they do not establish timing margins.
