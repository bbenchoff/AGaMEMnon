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
    expect_trace(4'b0010, 1);

    force dut.dut.command_htrans1 = 1'b0;
    // External order after HTRANS deasserts:
    // pending, start, three busy cycles, then retained sampled response.
    expect_trace(4'b0010, 2);
    expect_trace(4'b0001, 3);
    expect_trace(4'b0100, 4);
    expect_trace(4'b0100, 5);
    expect_trace(4'b1100, 6);
    expect_trace(4'b1000, 7);

    release dut.dut.command_htrans1;
    release dut.dut.command_word_select;
    $display("PASS: Pico trace pending/start/busy/sampled timeline");
    $finish;
  end
endmodule
