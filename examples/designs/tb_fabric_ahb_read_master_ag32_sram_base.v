`timescale 1ns/1ps
module tb_fabric_ahb_read_master_ag32_sram_base;
  reg start = 0;
  reg word_select = 0;
  wire busy, done, response_observation;

  agamemnon_fabric_ahb_read_master_ag32_sram_base dut (
    .start(start), .word_select(word_select), .busy(busy), .done(done),
    .response_observation(response_observation)
  );

  task launch;
    input select_word_1;
    begin
      word_select = select_word_1;
      start = 1'b1;
      @(posedge dut.hclk); #1;
      start = 1'b0;
      if (!busy || dut.control[0] || dut.control[3])
        $fatal(1, "request escaped before registered presentation");

      @(posedge dut.hclk); #1;
      if (!busy || !dut.control[0] || !dut.control[1] ||
          dut.control[3:2] !== 2'b10 || dut.control[6:4] !== 3'b010 ||
          dut.control[9:7] !== 3'b000 || dut.control[10])
        $fatal(1, "exact request controls are not a word NONSEQ read");
      if (dut.haddr2_presented !== select_word_1)
        $fatal(1, "bounded address word selection changed");

      @(posedge dut.hclk); #1;
      if (!dut.control[0] || dut.control[3:2] !== 2'b10 ||
          !dut.response_valid)
        $fatal(1, "request was not held through HREADYOUT completion");

      @(posedge dut.hclk); #1;
      if (dut.control[0] || dut.control[3:2] !== 2'b00 ||
          !done || busy || response_observation !== 1'b1)
        $fatal(1, "registered completion did not return to IDLE");
      @(posedge dut.hclk); #1;
      if (done)
        $fatal(1, "done is not a one-cycle pulse");
    end
  endtask

  initial begin
    wait (dut.hresetn === 1'b1);
    @(posedge dut.hclk); #1;
    if (busy || done || dut.control[0] || dut.control[3:2] !== 2'b00 ||
        dut.control[10])
      $fatal(1, "exact-source wrapper is not reset-idle");

    launch(1'b0);
    launch(1'b1);

    $display("PASS: exact-source SRAM-base read observer registered presentation");
    $finish;
  end
endmodule
