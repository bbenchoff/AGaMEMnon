`timescale 1ns/1ps
module tb_fabric_ahb_read_observer_endpoint;
  agamemnon_fabric_ahb_read_observer_endpoint dut();
  integer busy_cycles = 0;
  integer done_pulses = 0;

  always @(posedge dut.master.hclk) begin
    if (dut.busy)
      busy_cycles = busy_cycles + 1;
    if (dut.done)
      done_pulses = done_pulses + 1;
  end

  initial begin
    wait (dut.master.hresetn === 1'b1);
    repeat (8) @(posedge dut.master.hclk);
    if (busy_cycles != 0 || done_pulses != 0)
      $fatal(1, "observer issued a request without an MCU transaction");

    force dut.command_word_select = 1'b0;
    force dut.command_htrans1 = 1'b1;
    repeat (8) @(posedge dut.master.hclk);
    force dut.command_htrans1 = 1'b0;
    repeat (8) @(posedge dut.master.hclk);
    if (done_pulses != 1)
      $fatal(1, "first command did not emit exactly one bounded read");

    // Re-reading one command address cannot create another request.
    force dut.command_htrans1 = 1'b1;
    repeat (8) @(posedge dut.master.hclk);
    force dut.command_htrans1 = 1'b0;
    repeat (8) @(posedge dut.master.hclk);
    if (done_pulses != 1)
      $fatal(1, "same-address poll emitted background bus traffic");

    // An address transition admits one new request.
    force dut.command_word_select = 1'b1;
    force dut.command_htrans1 = 1'b1;
    repeat (8) @(posedge dut.master.hclk);
    force dut.command_htrans1 = 1'b0;
    repeat (8) @(posedge dut.master.hclk);
    #1;
    if (busy_cycles != 6 || done_pulses != 2)
      $fatal(1, "transaction-triggered observer cadence changed");
    if (dut.master.selected_word !== 1'b1 || dut.endpoint_ready !== 1'b1 ||
        dut.endpoint_okay !== 1'b0)
      $fatal(1, "observer endpoint contract changed");
    if (!dut.response_valid || dut.response_sampled !== 1'b1)
      $fatal(1, "observer did not retain a presented response");
    release dut.command_htrans1;
    release dut.command_word_select;
    $display("PASS: transaction-triggered fabric AHB observer endpoint cadence");
    $finish;
  end
endmodule
