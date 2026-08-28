# R10 two-stage master-state observer desk candidate

Status: **desk-accepted candidate; no hardware authority**.

R10 is a valid bounded non-perturbing follow-up to the R9 negative. R9 moved the functional master-state
flops onto the four-pad observation tile and therefore changed the circuit being observed. R10 starts from
accepted R8 commit `d3eac96dd716810cacd88372a3e1ac446661f9e1`, retains the exact R8 functional
placement and routing, and changes only the observer endpoints.

The first registered copies remain at `X14Y11_SLICE4/5`, exactly as in R8. Their same-clock second copies
occupy `X14Y11_SLICE6/7`. PIN25/PIN26 expose the first-stage bits and PIN27/PIN28 expose the second-stage
bits. The active and control sources differ only in `REQUEST_ENABLE`; the canonical routed pair differs
only in `dut.request_arm_source_LC.INIT`.

## Preservation proof

The R8 and R10 synthesized designs each contain 145 cells and 61 source nets. A fail-closed composer maps
all 145 cells, including the 19 deterministic synthesized LUTs and the four renamed observer cells. Every
cell type and parameter matches. All R8 BELs are replayed.

Exactly four endpoint signatures change:

- the two first-stage Q nets gain the two second-stage D sinks;
- `start_pulse` and `command_pending` lose their old R8 trace-only sinks.

Every other endpoint signature, BEL, and routed edge is exact. Router2 imports the checkpoint with zero
ordinary arcs to route. It prunes only the now-obsolete trace branches and adds exactly four new observer
edges. The functional master retains all 102 cells and every pre-existing route edge; the new state-Q
fanout is additive.

Strict bitgen reports 565 data PIPs, 484 configurable mapped PIPs, 282 block-clean and 36 relative-clean
selectors, with zero unmapped, predicted, or legacy-absolute selectors. All four typed L48 output lanes
close. Repacking both arms twice reproduces raw images, compressed images, and policy sidecars
byte-identically.

## Exact artifacts

The retained R8 route is 169,051 bytes, SHA-256
`24120f2812251721f6d9441b294d49747b0ad1677d5841497522f8d9fcf2efa3`.

The canonical R10 active route is 188,510 bytes,
`a73793f4b2731de493c0f6f084613cae614e6c6f170caaa2408dfb65766bec52`; its image is
`07d1cf69fed22e0a4e484eaeaba540dbd6ff9e9c404a4fb21ffd663e30a1fba8`.

The canonical control route is 188,508 bytes,
`9a70458db084eb101789b80197e16ccd835605db669157c82e5d82b4f5b4ebab`; its image is
`b5006e22c749bbcfb67ab3db29b4bc669723083c1b598135d3907c21cecb996c`.

The images differ at body offsets 2747, 2863, 2979, and 3095 plus CRC offsets 99940 through 99943.
The full machine-readable record is `qualification/r10_two_stage_state_pipeline_desk_audit.json`.

## Bounded capture classifier

Decode the sparse Pico capture to a logical nibble with the second stage in bits 3:2 and the first stage
in bits 1:0. Admit only one repeated sequence:

- `1,7,14,8`: both stages show the complete ADDR/PRESENT/DATA progression;
- `1,6,8`: the first stage omits PRESENT and the second stage follows it;
- `1,7,10,8`: the first stage shows PRESENT but the second stage omits it.

Each phase may occupy one to three samples. For the full sequence only, one sample may bridge each
transition: 3 or 5 between 1 and 7, 6 or 15 between 7 and 14, and 10 or 12 between 14 and 8. Require zero
at both capture boundaries, at least three zero samples between transactions, at least 16 complete
transactions, and zero control activity. Reject foreign, reordered, truncated, or mixed sequences.

This desk result provides no hardware authority, silicon result, response-field interpretation, timing
or skew claim, generalized placement claim, or retry authority.
