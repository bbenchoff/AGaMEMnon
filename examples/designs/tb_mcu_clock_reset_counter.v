`timescale 1ns/1ps

module tb_mcu_clock_reset_counter;
  top dut();

  initial begin
    #12;
    if (dut.toggle !== 1'b0) begin
      $display("FAIL: toggle was not reset: %b", dut.toggle);
      $fatal(1);
    end
    #15;
    if (dut.toggle !== 1'b1) begin
      $display("FAIL: first post-reset clock did not toggle: %b", dut.toggle);
      $fatal(1);
    end
    #10;
    if (dut.toggle !== 1'b0) begin
      $display("FAIL: second post-reset clock did not toggle: %b", dut.toggle);
      $fatal(1);
    end
    $display("PASS: typed MCU clock/reset simulation");
    $finish;
  end
endmodule
