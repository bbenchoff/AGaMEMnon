`timescale 1ns/1ps

module tb_mcu_ahb_constant_slave;
  top dut();
  initial begin
    #1;
    if (dut.endpoint.hreadyout !== 1'b1) $fatal(1, "HREADYOUT is not ready");
    if (dut.endpoint.hresp !== 1'b0) $fatal(1, "HRESP is not OKAY");
    if (dut.endpoint.hrdata !== 32'h4147_414d) $fatal(1, "bad ID word");
    $display("PASS: constant-ready OKAY AHB endpoint");
    $finish;
  end
endmodule
