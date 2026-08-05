// Cause-19 placement variant of the qualified write-command controller.
// State semantics and the constant-zero read boundary remain identical to the
// cause-17 controller; only the exact qualified output BEL/sink changes.
`define AGAMEMNON_LOCAL_INT3
`include "qualification/mcu_ahb_local_int1_bank.v"
