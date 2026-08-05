// Cause-16 composite-command variant of the qualified controller.
// HADDR2 selects one write class; HADDR3 is intentionally ignored, making
// offsets 4 and C explicit aliases. Data commands are 00=mask off/pending
// hold, 01=mask on/ack, 10=mask off/set, and 11=mask on/set.
`define AGAMEMNON_LOCAL_INT0
`include "qualification/mcu_ahb_local_int1_bank.v"
