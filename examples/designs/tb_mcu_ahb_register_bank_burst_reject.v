`timescale 1ns/1ps

module tb_mcu_ahb_register_bank_burst_reject;
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

  task automatic transfer(input [31:0] addr, input wr, input [2:0] burst,
                          input [31:0] wdata, input expect_error,
                          output reg [31:0] rdata);
    integer guard;
    begin
      @(negedge hclk);
      hsel = 1; haddr = addr; htrans = 2'b10; hwrite = wr;
      hsize = 2; hburst = burst;
      @(posedge hclk); #1;
      if (hreadyout !== 1'b0) $fatal(1, "configured wait missing");
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0; hburst = 0; hwdata = wdata;
      guard = 0;
      while (!hreadyout) begin
        @(posedge hclk); #1; guard = guard + 1;
        if (guard > 3) $fatal(1, "deadlock");
      end
      if (hresp !== expect_error)
        $fatal(1, "HBURST=%0d HRESP=%b expected=%b", burst, hresp,
               expect_error);
      rdata = hrdata;
      @(posedge hclk); #1;
    end
  endtask

  integer burst;
  reg [31:0] data;
  initial begin
    repeat (2) @(posedge hclk);
    hresetn = 1;

    transfer(BASE + 4, 1, 0, 32'h0000_005a, 0, data);
    if (scratch !== 32'h0000_005a) $fatal(1, "SINGLE seed failed");

    for (burst = 1; burst < 8; burst = burst + 1) begin
      transfer(BASE + 4, 1, burst[2:0], 32'h0000_00a0 + burst, 1, data);
      if (scratch !== 32'h0000_005a)
        $fatal(1, "HBURST=%0d mutated scratch to %08x", burst, scratch);
      transfer(BASE + 4, 0, burst[2:0], 0, 1, data);
      if (data !== 0)
        $fatal(1, "HBURST=%0d invalid read leaked %08x", burst, data);
    end

    transfer(BASE + 4, 0, 0, 0, 0, data);
    if (data !== 32'h0000_005a) $fatal(1, "SINGLE readback changed");
    $display("PASS: non-SINGLE HBURST values fail closed without mutation");
    $finish;
  end
endmodule
