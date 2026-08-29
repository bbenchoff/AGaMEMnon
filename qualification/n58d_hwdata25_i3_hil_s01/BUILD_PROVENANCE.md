# N5.8D build provenance

The authoritative fabric products came from two independent output roots using
the compiler source at `12866be4074ac93243b5bde6e7a4994f47ad918f`, Yosys
0.33 (`2584903a060`), nextpnr executable SHA-256
`7cd68e32fddc31b7261ce05e89a338443dbe433f261bbec3cdc57bea75f58260`,
and freshly generated `devdb_strict_pcf` tables matching the accepted N5.8A
database hashes.

Both roles used:

```text
python -m agamemnon.cli build <role>.v -o <root>/<role>.bin --top top
  --pcf qualification/n58d_hwdata25_i3_hil_s01/pin18_L48.pcf
  --device AGRV2KL48 --part AG32VF303CCT6 --uarch --release-strict
  --write-routed <root>/<role>_routed.raw.json
```

The candidate nextpnr command included `--placer heap --seed 1`. The control
command omitted explicit placer and seed arguments and used the CLI's fixed
conduction placement policy: cap 2, internal seed 4. The package manifest binds
these role-specific facts separately.

Exact products from roots A and B:

| Product | Size | SHA-256 |
|---|---:|---|
| candidate.bin | 99,944 | `199f1ee7b538c8331a32f5e7e8def0b26f045806970886f645cc07922914f54a` |
| candidate.bin.comp | 2,947 | `d8388d8b59b7e81924e612bcc802f2d46efced9ebcfe2f52a810e3514291b469` |
| candidate routed raw JSON | 6,792 | `a336b55a9af7adc0103b179eaec7d8df24b7eb5111ac440bf325b5fd077c6a1f` |
| candidate routed canonical JSON | 6,816 | `108f2368e5e450c0d4a2bac19070f14e2d4431b6c181b8d432c5977c4636ff57` |
| control.bin | 99,944 | `d57da9dd3bb4141f10e5cc1289dfdad1f500cf9a9ad21ac6345bfe412558ae65` |
| control.bin.comp | 2,902 | `bb402d29f20094e4f3f9a36228d837d2157472f06faf8bde8b7a9bee0c020989` |
| control routed raw JSON | 5,277 | `268a549f41b20ee2ac3f58ee85e02600e7c33971ca8381ada58e95580be05b31` |
| control routed canonical JSON | 5,296 | `1bbf652eaa3f7149c8e1709777ec20d2bace3303cc01ece82c852135ff7af531` |
| stimulus.elf | 4,728 | `64ce17536d59d9bb809241a48c40d21f110e0b66c5480d486c734fd8962b4566` |
| stimulus.bin | 112 | `1a80a41d8eba976f396d2982c81db8aba4809834642be44e91a0a5650826f228` |

The first exploratory invocation stopped after route validation because its
requested output directory did not exist; bitgen reported `FileNotFoundError`
before emitting an image. Two later exploratory builds used a different local
Yosys 0.66 and were not promoted. Their images and routed artifacts are not
package authority. The exact Yosys 0.33 pair above is the sole source of the
tracked fabric artifacts.
