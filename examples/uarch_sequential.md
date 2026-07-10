# Multi-bit sequential logic through the `agrv2k` uarch (silicon-proven)

This example runs **real multi-bit sequential logic on silicon through the fully-open `agrv2k` nextpnr
uarch** — the shippable backend (`nextpnr-generic --uarch agrv2k`). It is the milestone that makes the
uarch a *sequential* backend, not just a combinational one.

`examples/designs/counter_ahb.v` is a 4-bit counter whose bit 0 and bit 3 are read back over the MCU AHB
bus (`0x60000000`). Bit 3 only cycles when the carry propagates through all four bits, so observing all
four `(bit3,bit0)` states proves genuine multi-bit compute (not a stuck or toggle-only output).

**Silicon result:** `distinct=4` (values `0xc,0xd,0xe,0xf`, both read bits cycling) — it computes.

## Why this needs more than stock nextpnr

The AGRV2K fabric has two properties the open flow had to solve, both cracked here:

1. **Only some pips physically conduct.** A byte-correct config can still route through an electrically
   dead pip. So the device database is emitted **conduction-gated** (only silicon-conducting pips), and the
   uarch's `tile_adj` conducting graph is built from those same pips — placer and router agree exactly.
2. **Self-feedback + placement must conduct.** Registered feedback uses the slice's internal `Qin` path
   (`qin_pack`); cells that talk to each other must sit on **conducting tile-pairs**, which the uarch's
   conduction-aware placer (`pack_condplace`) arranges; and high-fanout nets are split by `fanout_split`
   (net replication) so each copy fits the fabric's conducting-fanout budget.

## The flow

```
# 1. device: conduction-gated, with the hardware-carry pins + the CLKIN clock source
python engine/emit_uarch_db.py --arch engine/arch.py --data chipdb \
    --out engine/uarch/agrv2k/devdb_gate \
    --env AGAMEMNON_CONDUCTION_GATE=1 --env AGAMEMNON_HW_CARRY=1 --env AGAMEMNON_LEDPADS=1
cp chipdb/master_conduction.csv engine/uarch/agrv2k/devdb_gate/

# 2. synth (LUT logic + Qin self-feedback) -> fanout split
yosys -p 'read_verilog -lib synth/prims.v; read_verilog examples/designs/counter_ahb.v; \
          hierarchy -top top; proc; flatten; tribuf -logic; deminout; synth -run coarse; opt -full; \
          techmap -map +/techmap.v; opt -fast; dfflegalize -cell $_DFF_P_ 0; abc -lut 4 -dress; clean; \
          techmap -D LUT_K=4 -map synth/cells_map.v; clean; \
          iopadmap -bits -inpad GENERIC_IOB O:PAD -outpad GENERIC_IOB I:PAD; clean; write_json counter.json'
python engine/qin_pack.py counter.json
python engine/fanout_split.py counter.json 2          # net replication, MAXFO=2

# 3. place & route: conduction-aware placer on the gated device
AGRV2K_CONDPLACE=1 AGRV2K_CONDPLACE_CAP=2 \
    nextpnr-generic --uarch agrv2k -o chipdb=engine/uarch/agrv2k/devdb_gate \
    --json counter.json --write counter_routed.json

# 4. open bitgen (mesh-template crossbar resolver + CLKIN clock)
AGAMEMNON_MESH_TEMPLATE=1 AGAMEMNON_LEDPADS=1 python engine/to_bin.py counter_routed.json counter.bin

# 5. silicon: SRAM-inject and read 0x60000000 -> distinct values = it computes
#    (the workbench's tools/ahb_read_run.py drives the OpenOCD inject + AHB read)
```

## Status and limits (honest)

**Proven on silicon:** toggle FF, 2-bit counter, 4-bit counter — all read back distinct values through the
uarch. This is the sequential foundation.

**Not yet — the SERV-scale goal.** A full soft RISC-V core (~1800 cells) does **not** route through this
flow yet. The conduction-aware placer is a greedy/backtracking embedder that caps at roughly 10–15 cells:
an 8-bit counter (≈26 cells after fanout splitting) already fails to embed on the sparse conducting graph.
Getting to SERV needs a **scalable conduction-aware placer** — an analytical/force-directed initial
placement with local conduction refinement (or seeding nextpnr's HeAP/SA with a conduction-aware start) —
plus BRAM program-memory integration and pad-output for a physical LED. Those are the next milestones; the
sequential path they build on is what this example proves works.

Also banked (built, silicon-diagnosed, deferred): the dedicated hardware-carry chain for wide arithmetic —
see the README "Banked" section. Wide arithmetic here runs via LUT + mesh carry instead.
