# Rejected X14Y10 I2 candidate

Status: **REJECTED before route and before image emission**

This child preserves the rejected fixed-site `X14Y9_SLICE0.I2` record and
tests the nearest raw directed-graph I2 sink, `X14Y10_SLICE0.I2`.  It is a
negative compiler result, not a hardware result.

Exact inputs:

- parent: `9a286c16cf79d18e257960a608fa7e2372788b6a`
- compiler commit: `12866be4074ac93243b5bde6e7a4994f47ad918f`
- candidate source size: 931 bytes
- candidate source SHA-256:
  `958c9d46e17aa01b99139bfee54c7ca106d07950929063d15018ab2b221716d1`
- control source size: 370 bytes
- control source SHA-256:
  `2f0f2ae4ea5def9ccbeb08a541660c16b3a35bf988d7e4f3c0d4b258de531f85`
- requested BEL/pin: `X14Y10_SLICE0.I2` / `X14Y10_IMUX02`
- LUT function: `INIT=F0F0`, identity on I2

The regenerated strict directed graph contains this raw path after the
mandatory first hop:

```text
X13Y9_InputMUX06 -> X14Y9_RMUX55 -> X14Y10_RMUX40 -> X14Y10_IMUX02
```

The exact release-strict source-to-image build nevertheless exhausted all 40
deterministic route attempts (including its final LUT-carry fallback) and
rejected every attempt before routing with:

```text
cell 'hwdata25_i2_identity' at X14Y10_SLICE0 cannot conduct fixed input net 'hwdata25' from 'mcu_hwdata25'
```

This rejection is correct.  Raw wire reachability alone is insufficient: the
typed HWDATA25 entry corridor is the single `Y9` slice row, while this sink is
on `Y10`.  The compiler therefore fails closed even though the unqualified
directed resource graph has a path.

No candidate image, routed artifact, controller package, authorization, or
evidence was produced.  Hardware was not contacted.  This candidate must not
be retried or amended; the next child must remain on `Y9` and independently
satisfy both typed input-corridor legality and output-pad reachability.
