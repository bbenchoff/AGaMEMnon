`timescale 1ns/1ps

module tb_mcu_ahb_register_bank;
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
  reg [31:0] status_set = 0;
  wire [31:0] hrdata, scratch, counter, status;
  wire hreadyout;
  wire hready = hreadyout;
  wire hresp;

  always #5 hclk = ~hclk;

  agamemnon_ahb_register_bank #(
    .BASE_ADDR(BASE), .ID_VALUE(32'h4147_414d), .WAIT_STATES(1)
  ) dut (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(hsel), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .STATUS_SET(status_set),
    .SCRATCH(scratch), .COUNTER(counter), .STATUS(status)
  );

  task automatic transfer(input [31:0] addr, input wr, input [2:0] size,
                          input [31:0] wdata, output reg resp,
                          output reg [31:0] rdata);
    integer guard;
    begin
      @(negedge hclk);
      hsel = 1; haddr = addr; htrans = 2'b10; hwrite = wr; hsize = size;
      @(posedge hclk); #1;
      if (hreadyout !== 1'b0) $fatal(1, "configured wait state missing");
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0; hwdata = wdata;
      guard = 0;
      while (!hreadyout) begin
        @(posedge hclk); #1;
        guard = guard + 1;
        if (guard > 3) $fatal(1, "register bank deadlocked");
      end
      resp = hresp;
      rdata = hrdata;
      @(posedge hclk); #1;
    end
  endtask

  reg response;
  reg [31:0] data;
  reg [31:0] counter_before;
  initial begin
    repeat (2) @(posedge hclk);
    hresetn = 1;

    transfer(BASE, 0, 2, 0, response, data);
    if (response || data !== 32'h4147_414d) $fatal(1, "bad ID response");

    transfer(BASE + 4, 1, 2, 32'h1122_3344, response, data);
    transfer(BASE + 5, 1, 0, 32'h0000_00aa, response, data);
    transfer(BASE + 6, 1, 1, 32'h0000_beef, response, data);
    transfer(BASE + 4, 0, 2, 0, response, data);
    if (response || data !== 32'hbeef_aa44) $fatal(1, "scratch mismatch %08x", data);

    counter_before = counter;
    transfer(BASE + 8, 0, 2, 0, response, data);
    if (response || data <= counter_before) $fatal(1, "counter did not advance");

    @(negedge hclk); status_set = 32'h0000_000f;
    @(posedge hclk); #1;
    @(negedge hclk); status_set = 0;
    transfer(BASE + 12, 1, 2, 32'h0000_0005, response, data);
    transfer(BASE + 12, 0, 2, 0, response, data);
    if (response || data !== 32'h0000_000a) $fatal(1, "W1C mismatch %08x", data);

    transfer(BASE, 1, 2, 32'h0, response, data);
    if (!response) $fatal(1, "write to read-only ID did not error");
    transfer(BASE + 5, 0, 1, 0, response, data);
    if (!response) $fatal(1, "misaligned halfword did not error");
    transfer(BASE + 16, 0, 2, 0, response, data);
    if (!response) $fatal(1, "out-of-range read did not error");

    $display("PASS: MCU AHB register bank ID/scratch/counter/W1C/wait/error");
    $finish;
  end
endmodule
