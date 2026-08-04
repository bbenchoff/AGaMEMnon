`timescale 1ns/1ps

// Protocol-timing check for the AG32 write-data boundary. Each write inserts
// one wait cycle, captures HWDATA once at the hard boundary, then retires from
// the captured value. Reads retain the ordinary zero-wait data phase.
module tb_mcu_ahb_register_bank_pipelined;
  localparam [31:0] BASE = 32'h6000_0000;
  reg hclk = 0;
  reg hresetn = 0;
  reg hsel = 0;
  reg [31:0] haddr = 0;
  reg [1:0] htrans = 0;
  reg hwrite = 0;
  reg [2:0] hsize = 2;
  reg [2:0] hburst = 0;
  reg [31:0] hwdata = 0;
  wire [31:0] hrdata, scratch, counter, status;
  wire hreadyout, hresp;
  wire hready = hreadyout;

  always #5 hclk = ~hclk;

  agamemnon_ahb_register_bank #(
    .BASE_ADDR(BASE), .WAIT_STATES(0), .PIPELINE_WRITE_DATA(1)
  ) dut (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(hsel), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .STATUS_SET(32'b0),
    .SCRATCH(scratch), .COUNTER(counter), .STATUS(status)
  );

  task automatic address_phase(input [31:0] addr, input wr);
    begin
      @(negedge hclk);
      if (!hreadyout) $fatal(1, "address phase started while bus stalled");
      hsel = 1; haddr = addr; htrans = 2'b10; hwrite = wr; hsize = 3'd2;
    end
  endtask

  task automatic finish_address(input [31:0] data);
    begin
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0; hwdata = data;
    end
  endtask

  task automatic complete_write(input [31:0] data);
    begin
      finish_address(data);
      if (hreadyout !== 1'b0) $fatal(1, "pipelined write omitted wait");
      if (scratch !== 32'b0) $fatal(1, "write committed before capture");
      @(negedge hclk);
      if (hreadyout !== 1'b1) $fatal(1, "pipelined write wait exceeded one cycle");
      @(negedge hclk);
    end
  endtask

  initial begin
    repeat (4) @(negedge hclk);
    hresetn = 1;
    repeat (2) @(negedge hclk);

    address_phase(BASE + 4, 1'b1);
    complete_write(32'h0000_00a5);
    if (scratch !== 32'h0000_00a5) $fatal(1, "captured write data wrong");

    // Write followed immediately by a read address. The read data phase must
    // observe the value committed on the preceding write completion edge.
    address_phase(BASE + 4, 1'b1);
    finish_address(32'h0000_003c);
    if (hreadyout !== 1'b0) $fatal(1, "second write omitted wait");
    @(negedge hclk);
    if (hreadyout !== 1'b1) $fatal(1, "second write wait exceeded one cycle");
    hsel = 1; haddr = BASE + 4; htrans = 2'b10; hwrite = 0;
    @(negedge hclk);
    hsel = 0; htrans = 0;
    if (hreadyout !== 1'b1 || hresp !== 1'b0)
      $fatal(1, "zero-wait read did not complete");
    if (hrdata !== 32'h0000_003c)
      $fatal(1, "write-then-read observed stale data");
    @(negedge hclk);

    // Two writes with no idle transfer between their completion/address
    // phases exercise the legal AHB back-to-back overlap.
    address_phase(BASE + 4, 1'b1);
    finish_address(32'h0000_0011);
    if (hreadyout !== 1'b0) $fatal(1, "back-to-back write A omitted wait");
    @(negedge hclk);
    if (!hreadyout) $fatal(1, "back-to-back write A did not become ready");
    hsel = 1; haddr = BASE + 4; htrans = 2'b10; hwrite = 1;
    @(negedge hclk);
    hsel = 0; htrans = 0; hwrite = 0; hwdata = 32'h0000_0022;
    if (hreadyout !== 1'b0) $fatal(1, "back-to-back write B omitted wait");
    @(negedge hclk);
    if (!hreadyout) $fatal(1, "back-to-back write B did not become ready");
    @(negedge hclk);
    if (scratch !== 32'h0000_0022) $fatal(1, "back-to-back write value wrong");

    $display("PASS: pipelined MCU AHB write boundary timing");
    $finish;
  end
endmodule
