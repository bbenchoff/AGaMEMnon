# The AG32 config-surface partition — the map to "completely open" + vendor parity

> Working model (2026-08-13) for decoding the *entire* AGRV2K configuration bitstream, so the
> open flow both **generates** every bit from scratch (no vendor canvas) and **knows** what every
> bit does (vendor parity). Grounded in the measured canvas decode
> ([FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md)) and sharpened by an insight: the big
> undecoded region is *cell/routing config*, and whatever falls outside it is *config for
> something else* — the subsystems and peripherals.

## The three planes

The 99,936-byte raw config decomposes into distinct **planes**, each a different *kind* of config:

1. **LUT function plane** — the logic-cell truth tables (`LUT INIT`). **Decoded**
   (`physmap.init_bit_pos`, 33,792 positions; unconfigured default `0x00`). This is *what each
   cell computes*.
2. **Routing / cell-interconnect plane** — the mux/selector fabric (`CFG_RMUX / IMUX / OMUX /
   CTRLMUX / SEAMMUX / BBMUXS / IOMUX`). This is *how the cells connect* — "what the cells do" in
   the wiring sense. It is the big `0xFF` region of the canvas (four aligned rectangles over the
   116-byte word-line grid — the main block cols 59-114 plus top/bottom seam-selector bands —
   28,570 body bytes / 228,560 bits at their all-ones reset default). Position and reset value are
   fully decoded and generated from scratch; **~26% of bit-line *functions* named, ~74% not yet
   mapped** to resources. Full decode = the per-LogicTile bit-line→resource map (promoted
   2026-08-14 as `agamemnon/chipdb/logictile_config_template.csv`).
3. **Subsystem / peripheral config plane** — everything that is neither a logic cell nor a fabric
   route: clock/PLL (in the preamble, decoded), IO electrical / OE / bank config, BRAM
   modes/ports, and the hard-block edge interfaces. This is the *"config for something else"* —
   and it is exactly the peripheral surface.

## The insight, expanded

The read: *the big undecoded region is probably the config bits for the cells (what they do);
what we don't know is probably config for something else.* Measurement supports it — the `0xFF`
region sits in the routing/mux families, so it IS the cell-interconnect plane at default. That
reframes the whole "completely open" problem as **decode each plane**:

- Plane 1 (LUT function): **done**.
- Plane 2 (routing/cell config): the crossbar bit-line map is promoted and applied — every
  reserved bit-line has `{position, reset}`, and the canvas-retirement half landed 2026-08-14
  (the from-scratch base is the default). The know-every-bit half stays open: naming the
  *function* of the unnamed ~74% completes routing vendor parity.
- Plane 3 (subsystem/peripheral config): decode each subsystem's config → this is *"knowledge of
  all the peripherals."*

**Completely open = generate all three planes from the arch DB. Vendor parity = know what every
bit in all three planes does. They are the same decode, viewed two ways.**

## Roadmap

| Plane / surface | Decode state | To close it |
|---|---|---|
| LUT function | ✅ decoded | — |
| Routing / cell interconnect | ✅ position+reset decoded, generated 100% from scratch (promoted `logictile_config_template.csv` + `border_edge_partial_cells.csv`, 2026-08-14); ⚠️ ~74% of bit-line *functions* unnamed | name the unnamed ~74% bit-line functions and the 15 `XXXX` spares |
| Clock / PLL | ✅ decoded (preamble) | — |
| IO electrical / OE / bank | ⚠️ partial | per-pad/bank config decode (some in `io_evidence`) |
| BRAM modes / ports | ⚠️ subset | width / mode / port / collision config decode |
| Hard-block edge (MCU-AHB, DMA, interrupts) | ⚠️ subset qualified | the MCU-edge + peripheral-interface decode |
| Hard MMIO peripherals | ⚠️ subset qualified | full peripheral catalog + qualification (tracked in the peripheral catalog) |

`hypothesis` markers: plane-2 = cell-interconnect is measurement-backed (family overlap); the
crossbar table is promoted and supplies position/reset for every reserved bit-line, but the
per-bit *function* of the unnamed ~74% remains unproven; the
plane-3 boundary (which residue bits are IO vs BRAM vs hard-block) is a working partition, not yet
bit-exact. The config-plane decode (planes 1-2) is tracked in
[FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md); the peripheral surface (plane 3 + the hard
MMIO blocks) is tracked in the peripheral catalog.
