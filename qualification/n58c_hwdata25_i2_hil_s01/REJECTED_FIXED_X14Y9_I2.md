# Rejected fixed-site HWDATA25 I2 desk candidate

Status: `REJECTED_FAIL_CLOSED_NO_IMAGE`

The first N5.8C attempt retained the silicon-accepted endpoint, mandatory
first hop, slice site `X14Y9_SLICE0`, output pin, control, stimulus, and
capture concept while changing only the LUT terminal to I2/`X14Y9_IMUX02`
with `INIT=F0F0`.

Frozen rejected source:

- `candidate.v` size: 903 bytes
- `candidate.v` SHA-256:
  `9848739447efc0649d5eb9ab8ff502b0cac6ec0480c99b804f795596c1775bee`
- compiler commit: `12866be4074ac93243b5bde6e7a4994f47ad918f`
- nextpnr executable SHA-256:
  `7cd68e32fddc31b7261ce05e89a338443dbe433f261bbec3cdc57bea75f58260`
- admission: `devdb_strict_pcf`, release-strict

The exact source-to-image command exhausted 40 deterministic route attempts
and the one LUT-carry fallback. Every attempt rejected placement before route
completion with the same decisive validity result:

```text
agrv2k validity: typed HWDATA25 first-hop class cannot reach
X14Y9_SLICE0.I[2] for 'hwdata25_i2_identity'
ERROR: Bel 'X14Y9_SLICE0' of type 'GENERIC_SLICE' is not valid for cell
'hwdata25_i2_identity' of type 'GENERIC_SLICE'
```

No routed JSON, bitstream, GO, evidence directory, or hardware contact was
produced. This is not a silicon-negative result and does not justify adding a
graph edge or selector. The strict graph also reports `X14Y9_SLICE0.I3` as
unreachable from `X13Y9_InputMUX06`.

The nearest strict-graph I2 discriminator is a distinct child candidate at
`X14Y10_SLICE0.I2`, reached by:

```text
X13Y9_InputMUX06 -> X14Y9_RMUX55 -> X14Y10_RMUX40 -> X14Y10_IMUX02
```

That child necessarily changes the slice site and output route as well as the
terminal, so it must remain a separately preregistered composition.
