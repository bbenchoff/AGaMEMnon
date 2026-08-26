`timescale 1ns/1ps
module tb_fabric_ahb_read_master_ag32;
  reg start = 0;
  reg [31:0] address = 0;
  wire busy, done, error, timed_out;
  wire [31:0] read_data;

  agamemnon_fabric_ahb_read_master_ag32 #(.TIMEOUT_CYCLES(3)) dut (
    .start(start), .address(address), .busy(busy), .done(done),
    .error(error), .timed_out(timed_out), .read_data(read_data)
  );

  initial begin
    wait (dut.hresetn === 1'b1);
    @(posedge dut.hclk); #1;
    if (busy || done || dut.hsel || dut.htrans !== 2'b00 || dut.hwrite)
      $fatal(1, "AG32 wrapper is not reset-idle");

    address = 32'h2000_0100;
    start = 1'b1;
    @(posedge dut.hclk); #1;
    start = 1'b0;
    if (!busy || !dut.hsel || dut.htrans !== 2'b10)
      $fatal(1, "AG32 wrapper did not issue NONSEQ address phase");
    if (dut.haddr !== address || dut.hwrite || dut.hsize !== 3'd2 ||
        dut.hburst !== 3'd0 || dut.hwdata !== 32'd0)
      $fatal(1, "AG32 wrapper request fields changed");

    @(posedge dut.hclk); #1;
    if (!busy || dut.hsel || dut.htrans !== 2'b00)
      $fatal(1, "AG32 wrapper did not return request to IDLE");
    @(posedge dut.hclk); #1;
    if (!done || busy || error || timed_out || read_data !== 32'd0)
      $fatal(1, "AG32 wrapper zero-wait response mismatch");

    $display("PASS: AG32 read-master wrapper reset-idle zero-wait binding");
    $finish;
  end
endmodule
