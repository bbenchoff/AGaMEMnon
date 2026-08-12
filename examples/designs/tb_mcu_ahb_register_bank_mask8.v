`timescale 1ns/1ps

module tb_mcu_ahb_register_bank_mask8;
  localparam [31:0] BASE = 32'h6000_0000;
  reg hclk = 0, hresetn = 0, hsel = 0, hwrite = 0;
  reg [31:0] haddr = 0, hwdata = 0, status_set = 0;
  reg [1:0] htrans = 0;
  reg [2:0] hsize = 2, hburst = 0;
  wire [31:0] hrdata, scratch, counter, status;
  wire hreadyout, hresp;
  wire hready = hreadyout;
  always #5 hclk = ~hclk;

  agamemnon_ahb_register_bank #(
    .BASE_ADDR(BASE), .ID_VALUE(32'h0000_004d), .WAIT_STATES(1),
    .WRITABLE_MASK(32'h0000_00ff), .ALLOW_BYTE(1)
  ) dut (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(hsel), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .STATUS_SET(status_set),
    .SCRATCH(scratch), .COUNTER(counter), .STATUS(status)
  );

  task automatic transfer(input [31:0] addr, input wr, input [2:0] size,
                          input [31:0] wdata, output reg [31:0] rdata);
    integer guard;
    begin
      @(negedge hclk);
      hsel = 1; haddr = addr; htrans = 2'b10; hwrite = wr; hsize = size;
      @(posedge hclk); #1;
      if (hreadyout !== 1'b0) $fatal(1, "configured wait missing");
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0; hwdata = wdata;
      guard = 0;
      while (!hreadyout) begin
        @(posedge hclk); #1; guard = guard + 1;
        if (guard > 3) $fatal(1, "deadlock");
      end
      if (hresp) $fatal(1, "unexpected response error");
      rdata = hrdata;
      @(posedge hclk); #1;
    end
  endtask

  reg [31:0] data;
  initial begin
    repeat (2) @(posedge hclk);
    hresetn = 1;
    transfer(BASE + 4, 1, 2, 32'h1122_3344, data);
    if (scratch !== 32'h44) $fatal(1, "masked word %08x", scratch);
    transfer(BASE + 4, 1, 0, 32'haa, data);
    if (scratch !== 32'haa) $fatal(1, "low byte %08x", scratch);
    transfer(BASE + 5, 1, 0, 32'hbb, data);
    if (scratch !== 32'haa) $fatal(1, "upper byte changed low byte");
    transfer(BASE + 4, 1, 1, 32'hbeef, data);
    if (scratch !== 32'hef) $fatal(1, "low half %08x", scratch);
    transfer(BASE + 6, 1, 1, 32'hcafe, data);
    if (scratch !== 32'hef) $fatal(1, "upper half changed low byte");

    @(negedge hclk); status_set = 1;
    @(posedge hclk); #1;
    @(negedge hclk); status_set = 0;
    transfer(BASE + 13, 1, 0, 32'h1, data);
    if (status !== 1) $fatal(1, "upper status byte cleared low bit");
    transfer(BASE + 12, 1, 0, 32'h1, data);
    if (status !== 0) $fatal(1, "low status byte did not clear");
    $display("PASS: masked low-byte subword semantics");
    $finish;
  end
endmodule
