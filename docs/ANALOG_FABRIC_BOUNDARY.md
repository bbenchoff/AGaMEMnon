# Analog/fabric boundary

## Silicon-qualified analog register path (L48, 2026-08-14)

The analog hard blocks are memory-mapped in the External-AHB window at
`0x60000000` (ADC0 `+0x0000`, ADC1 `+0x1000`, ADC2 `+0x2000`, DAC0 `+0x3000`,
DAC1 `+0x4000`, CMP0 `+0x5000`) and only exist once a fabric image instantiating
the analog IP wrapper has been configured. On that path the following are
**silicon-qualified**:

| Block | Evidence |
|---|---|
| ADC0, ADC1, ADC2 | 12-bit single-channel one-shot conversion tracking a DAC stimulus |
| DAC0, DAC1 | 10-bit output verified through ADC readback |
| CMP0 **unit 1** | output flips at the four internal VREF taps at the predicted codes |
| DAC0→ADC channel 4, DAC1→ADC channel 5 | internal loopback taps, present on all three ADC instances, no external analog wiring |
| External-AHB → APB analog register path | reads/writes of every register above from open MCU firmware |

Stimulus-response, not a constant readback. Sweeping DAC0 across
`{0,128,256,384,512,640,768,896,1023}` read back, **on one representative run**,
`0, 512, 1024, 1536, 2054, 2575, 3085, 3598, 4095` on ADC0 channel 4: strictly
monotonic, ~4.00x linear (the ideal 12-bit-result over 10-bit-code ratio) and
saturating at full scale. DAC1→channel 5 (on ADC0) and DAC0→ADC1/ADC2 channel 4
reproduce the behaviour.

> **That vector is a sample, not a constant.** This is a real analog converter
> and the low bits move between runs — an independent run of the identical sweep
> recorded `0, 511, 1024, 1538, 2054, 2573, 3085, 3594, 4095`. The qualified,
> run-invariant claims are **monotonic**, **~4.00x slope**, and **saturating**;
> anything asserting the exact codes will be flaky. Quote the vector as evidence
> of shape, never as an expected value. CMP0 unit 1, with DAC0 on its positive input, flipped at DAC0 codes
**94 / 188 / 281 / 373** for MSEL = VREF/4, VREF/2, 3·VREF/4, VREF — a clean
1:2:3:4 progression against the **93 / 186 / 279 / 372** predicted from the
vendor RTL.

**What this is not.** The MCU side is fully open — AGaMEMnon SDK drivers, SRAM
staging, FCB configuration, and External-AHB reads — but the fabric image
instantiates the **vendor `analog_ip` hard-macro wrapper**. AGaMEMnon's own
bitgen does not emit that macro, so this is a qualification of the analog blocks
and their register path on the L48 part, *not* a claim that the open flow can
synthesize or place the analog IP. The route support described below is a
separate, narrower thing.

**Honest negatives from the same runs:**

- **CMP0 unit 2 is UNPROVEN, not working.** It is register-readable and its
  enable bit takes (`CTRL` reads back `0x100`), but its output read high at every
  DAC0 code — both code 0 and code 1023 — under **both** PSEL2 selects. Its
  positive-input mux therefore maps to different nets than unit 1's in some
  undocumented way; the vendor example never exercised it.
- **External ADC channels 0–3 read full scale** (`0xfff`) because those analog
  pads are **not bonded on the L48 package**. A full-scale reading there is an
  unbonded rail, not a measurement, and L48 analog-pad bonding is not
  characterized here.
- CMP hysteresis and mode bits, ADC/DAC DMA and continuous-scan modes, and
  multi-entry sequencer runs are all unexercised.

The drivers are `sdk/include/ag32_adc.h`, `ag32_dac.h`, and
`ag32_comparator.h`; `examples/riscv_mcu/analog_probe.c` runs the sweep and the
comparator flip scan and reports both verdicts to the SRAM mailbox.

## Read-only ADC route support in the strict open flow

The strict open flow currently exposes three read-only analog hard-block
routes: `AGRV2K_ADC0_DB0`, `AGRV2K_ADC0_DB1`, and `AGRV2K_ADC0_EOC`. Raw
route-bar `src_sub` values 0, 1, and 12 match the decoded grid-pin ordering and
establish distinct hard-output identities even though vendor route.tx names all
three nets by the ADC cell instance. The public graph therefore gives each pin
a private synthetic first-exit wire before joining the shared fabric topology.

The DB0 and DB1 strict smokes each route seven pips and map five configurable
fields; their vendor oracles each pass 49 selector checks. EOC routes eight
pips, maps six fields, and passes 59 checks. All have zero unmapped pips and two
fixed hard-boundary hops. Reproducible hashes are recorded in the three
`qualification/analog_adc0_*_route_evidence.jsonl` ledgers.

This is route support only. AGaMEMnon does not configure or start the ADC, does
not arbitrate MCU/fabric ownership, and makes no ADC timing, electrical, or
silicon-function claim. DB0 and DB1 both use a symbolically named `InputMUX01`
in route.tx; their raw `src_sub` identities and private public exits prevent
that lossy name from merging the hard pins. The checked smoke images must not
be treated as board qualification images.

The remaining ten ADC0 data lanes and the fabric-to-ADC control corridors remain
unsupported in the open route graph. Register drivers and board-level analog
tests are no longer absent — see the qualified subset at the top of this
document — but they run against a vendor-macro fabric image, not an
open-emitted one.
