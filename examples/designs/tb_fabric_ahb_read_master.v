`timescale 1ns/1ps
module tb_fabric_ahb_read_master;
  reg clk = 0;
  reg resetn = 0;
  reg start = 0;
  reg [31:0] address = 0;
  reg readyout = 1;
  reg resp = 0;
  reg [31:0] rdata = 0;
  wire busy, done, error, timed_out;
  wire [31:0] read_data, haddr, hwdata;
  wire hsel, hready, hwrite;
  wire [1:0] htrans;
  wire [2:0] hsize, hburst;

  always #5 clk = ~clk;

  agamemnon_fabric_ahb_read_master #(.TIMEOUT_CYCLES(3)) dut (
    .HCLK(clk), .HRESETn(resetn), .start(start), .address(address),
    .busy(busy), .done(done), .error(error), .timed_out(timed_out),
    .read_data(read_data), .HSEL(hsel), .HREADY(hready), .HTRANS(htrans),
    .HSIZE(hsize), .HBURST(hburst), .HWRITE(hwrite), .HADDR(haddr),
    .HWDATA(hwdata), .HREADYOUT(readyout), .HRESP(resp), .HRDATA(rdata));

  task launch;
    input [31:0] addr;
    begin
      address = addr;
      start = 1;
      @(posedge clk); #1;
      start = 0;
      if (!busy || !hsel || htrans !== 2'b10 || haddr !== addr)
        $fatal(1, "bad address phase");
      if (hwrite || hsize !== 3'd2 || hburst !== 0 || hwdata !== 0)
        $fatal(1, "read-only constants changed");
      @(posedge clk); #1;
      if (hsel || htrans !== 0)
        $fatal(1, "next address phase is not IDLE");
    end
  endtask

  initial begin
    repeat (2) @(posedge clk);
    resetn = 1;
    @(posedge clk); #1;
    if (busy || done || hsel || htrans !== 0 || hwrite)
      $fatal(1, "master is not reset-idle");

    // Two inserted wait cycles, then a successful read.
    readyout = 0;
    launch(32'h2000_0100);
    repeat (2) begin
      if (!busy || hready) $fatal(1, "wait state not held");
      @(posedge clk); #1;
    end
    rdata = 32'hA5C3_7E19;
    readyout = 1;
    @(posedge clk); #1;
    if (!done || busy || error || timed_out || read_data !== 32'hA5C3_7E19)
      $fatal(1, "successful read result mismatch");

    // Error response completes without timeout.
    @(posedge clk); #1;
    resp = 1;
    launch(32'h2000_0200);
    @(posedge clk); #1;
    if (!done || !error || timed_out)
      $fatal(1, "error response not reported");
    resp = 0;

    // A permanently stalled slave terminates after the configured bound.
    @(posedge clk); #1;
    readyout = 0;
    launch(32'h2000_0300);
    repeat (3) @(posedge clk);
    #1;
    if (!done || busy || !error || !timed_out)
      $fatal(1, "timeout did not terminate transfer");
    readyout = 1;

    $display("PASS: reset-idle read master wait/error/timeout cases");
    $finish;
  end
endmodule
