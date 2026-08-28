`timescale 1ns/1ps
module tb_fabric_ahb_read_observer_pico_trace;
  wire [3:0] trace;
  top dut(.trace(trace));

  task expect_trace;
    input [3:0] expected;
    input integer stage;
    begin
      @(posedge dut.fabric_clock);
      #1;
      if (trace !== expected)
        $fatal(1, "trace stage %0d changed: got %04b expected %04b",
               stage, trace, expected);
    end
  endtask

  initial begin
    wait (dut.dut.fabric_resetn === 1'b1);
    repeat (4) @(posedge dut.fabric_clock);
    #1;
    if (trace !== 4'b0000)
      $fatal(1, "trace did not begin idle");

    force dut.dut.command_word_select = 1'b0;
    force dut.dut.command_htrans1 = 1'b1;
    // The endpoint first latches pending; the dedicated trace FF exposes it
    // one fabric edge later.
    expect_trace(4'b0000, 0);
    expect_trace(4'b1000, 1);

    force dut.dut.command_htrans1 = 1'b0;
    // External order after HTRANS deasserts:
    // pending, start, then the exact ADDR/PRESENT/DATA state encoding.
    expect_trace(4'b1000, 2);
    expect_trace(4'b0100, 3);
    expect_trace(4'b0001, 4);
    expect_trace(4'b0011, 5);
    expect_trace(4'b0010, 6);
    expect_trace(4'b0000, 7);

    release dut.dut.command_htrans1;
    release dut.dut.command_word_select;
    $display("PASS: Pico trace crossed master-state/pending/start timeline");
    $finish;
  end
endmodule
