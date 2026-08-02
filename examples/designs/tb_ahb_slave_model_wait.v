`timescale 1ns/1ps

module tb_ahb_slave_model_wait;
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
  wire hreadyout;
  wire hready = hreadyout;
  wire hresp;
  wire [31:0] hrdata;

  always #5 hclk = ~hclk;

  agamemnon_ahb_slave_model #(
    .BASE_ADDR(BASE), .WORDS(4), .WAIT_STATES(2)
  ) dut (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(hsel), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp)
  );

  task automatic address_phase(input [31:0] addr, input wr, input [2:0] size);
    begin
      @(negedge hclk);
      hsel = 1; haddr = addr; htrans = 2'b10; hwrite = wr; hsize = size;
      @(posedge hclk);
      #1;
      if (hreadyout !== 1'b0) $fatal(1, "wait state did not start");
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0;
    end
  endtask

  task automatic finish_transfer(input [31:0] data, output reg resp,
                                 output reg [31:0] rdata);
    integer low_cycles;
    begin
      hwdata = data;
      low_cycles = 0;
      while (!hreadyout) begin
        @(posedge hclk); #1;
        low_cycles = low_cycles + 1;
        if (low_cycles > 4) $fatal(1, "wait-state transfer deadlocked");
      end
      if (low_cycles != 2) $fatal(1, "expected two wait cycles, got %0d", low_cycles);
      resp = hresp;
      rdata = hrdata;
      @(posedge hclk); #1;
    end
  endtask

  reg response;
  reg [31:0] data;
  initial begin
    repeat (2) @(posedge hclk);
    hresetn = 1;

    address_phase(BASE, 1, 3'd2);
    finish_transfer(32'h1122_3344, response, data);
    if (response) $fatal(1, "word write errored");

    address_phase(BASE + 1, 1, 3'd0);
    finish_transfer(32'h0000_00aa, response, data);
    if (response) $fatal(1, "byte write errored");

    address_phase(BASE + 2, 1, 3'd1);
    finish_transfer(32'h0000_beef, response, data);
    if (response) $fatal(1, "halfword write errored");

    address_phase(BASE, 0, 3'd2);
    finish_transfer(0, response, data);
    if (response || data !== 32'hbeef_aa44)
      $fatal(1, "readback mismatch resp=%0d data=%08x", response, data);

    address_phase(BASE + 1, 0, 3'd1);
    finish_transfer(0, response, data);
    if (!response) $fatal(1, "misaligned halfword did not error");

    address_phase(BASE + 16, 0, 3'd2);
    finish_transfer(0, response, data);
    if (!response) $fatal(1, "out-of-range access did not error");

    $display("PASS: AHB slave wait/size/error transfers");
    $finish;
  end
endmodule
