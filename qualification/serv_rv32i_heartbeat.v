// Build the exact serv_rv32i_smoke program and datapath with its alternate
// repeated-success/JAL observation point.  Keeping the selection at compile
// time avoids perturbing the dense routed design with an extra input or output.
`define SERV_RV32I_HEARTBEAT
`include "qualification/serv_rv32i_smoke.v"
