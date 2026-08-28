`timescale 1ns/1ps
module tb_fabric_ahb_read_observer_pico_state_compare;
  wire [3:0] trace;
  top dut(.trace(trace));

  task expect_trace;
    input [3:0] expected;
    input integer stage;
    begin
      @(posedge dut.fabric_clock);
      #1;
      if (trace !== expected)
        $fatal(1, "state-compare stage %0d changed: got %04b expected %04b",
               stage, trace, expected);
    end
  endtask

  initial begin
    wait (dut.dut.fabric_resetn === 1'b1);
    repeat (4) @(posedge dut.fabric_clock);
    #1;
    if (trace !== 4'b0000)
      $fatal(1, "state-compare trace did not begin idle");

    force dut.dut.command_word_select = 1'b0;
    force dut.dut.command_htrans1 = 1'b1;
    expect_trace(4'b0000, 0);
    expect_trace(4'b0000, 1);

    force dut.dut.command_htrans1 = 1'b0;
    // Raw state occupies trace[1:0].  The same-clock registered copy occupies
    // trace[3:2] exactly one fabric edge later.
    expect_trace(4'b0000, 2);
    expect_trace(4'b0001, 3);
    expect_trace(4'b0111, 4);
    expect_trace(4'b1110, 5);
    expect_trace(4'b1000, 6);
    expect_trace(4'b0000, 7);

    release dut.dut.command_htrans1;
    release dut.dut.command_word_select;
    $display("PASS: Pico raw/registered master-state comparison timeline");
    $finish;
  end
endmodule
