`include "agamemnon/rtl/mcu_ahb_port.v"
`include "agamemnon/rtl/mcu_ahb_constant_slave.v"

(* top *) module top;
  agamemnon_mcu_ahb_constant_slave #(.READ_DATA(32'h4147_414d)) endpoint();
endmodule
