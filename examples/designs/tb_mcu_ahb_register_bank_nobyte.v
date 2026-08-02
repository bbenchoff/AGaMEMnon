`timescale 1ns/1ps

// Directed test for the ALLOW_BYTE=0 configuration used by the AG32 binding:
// byte-sized transfers must complete with HRESP=1 and leave state unchanged,
// while word and halfword transfers keep their normal behavior. HADDR[0] has
// no recovered LUT-input corridor on the AG32, so the binding cannot place
// byte lanes and must fail closed at the protocol level.
module tb_mcu_ahb_register_bank_nobyte;
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
    .BASE_ADDR(BASE), .ID_VALUE(32'h4147_414d), .WAIT_STATES(0), .ALLOW_BYTE(0)
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
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0; hwdata = wdata;
      #1;
      guard = 0;
      while (!hreadyout) begin
        @(negedge hclk); #1;
        guard = guard + 1;
        if (guard > 3) $fatal(1, "register bank deadlocked");
      end
      // Sample mid data phase: HRESP/HRDATA are combinational and clear at
      // the retiring clock edge.
      resp = hresp;
      rdata = hrdata;
      @(negedge hclk);
    end
  endtask

  reg resp;
  reg [31:0] rdata;

  initial begin
    repeat (4) @(negedge hclk);
    hresetn = 1;
    repeat (2) @(negedge hclk);

    // word write accepted
    transfer(BASE + 4, 1'b1, 3'd2, 32'hA5C3_F00F, resp, rdata);
    if (resp !== 1'b0) $fatal(1, "word write rejected");
    if (scratch !== 32'hA5C3_F00F) $fatal(1, "word write value wrong");

    // byte write rejected with error, scratch untouched
    transfer(BASE + 5, 1'b1, 3'd0, 32'h0000_5A00, resp, rdata);
    if (resp !== 1'b1) $fatal(1, "byte write not errored");
    if (scratch !== 32'hA5C3_F00F) $fatal(1, "byte write mutated scratch");

    // byte read rejected with error
    transfer(BASE + 0, 1'b0, 3'd0, 32'h0, resp, rdata);
    if (resp !== 1'b1) $fatal(1, "byte read not errored");

    // halfword write still accepted
    transfer(BASE + 6, 1'b1, 3'd1, 32'h0000_BEEF, resp, rdata);
    if (resp !== 1'b0) $fatal(1, "halfword write rejected");
    if (scratch !== 32'hBEEF_F00F) $fatal(1, "halfword write value wrong");

    // word read still returns ID
    transfer(BASE + 0, 1'b0, 3'd2, 32'h0, resp, rdata);
    if (resp !== 1'b0 || rdata !== 32'h4147_414d) $fatal(1, "word ID read wrong");

    $display("PASS: MCU AHB register bank ALLOW_BYTE=0");
    $finish;
  end
endmodule
