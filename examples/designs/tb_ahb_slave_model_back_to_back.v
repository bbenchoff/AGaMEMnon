`timescale 1ns/1ps

module tb_ahb_slave_model_back_to_back;
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

  agamemnon_ahb_slave_model #(.BASE_ADDR(BASE), .WORDS(4), .WAIT_STATES(0)) dut (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(hsel), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp)
  );

  initial begin
    repeat (2) @(posedge hclk);
    hresetn = 1;

    // Address phase for write 0.
    @(negedge hclk);
    hsel = 1; htrans = 2'b10; hwrite = 1; haddr = BASE; hsize = 2;
    @(posedge hclk); #1;

    // Data for write 0 overlaps address phase for write 1.
    @(negedge hclk);
    hwdata = 32'h1111_1111; haddr = BASE + 4;
    @(posedge hclk); #1;
    if (hresp) $fatal(1, "first back-to-back write errored");

    // Data for write 1; end the address pipeline.
    @(negedge hclk);
    hwdata = 32'h2222_2222; hsel = 0; htrans = 0; hwrite = 0;
    @(posedge hclk); #1;
    if (hresp) $fatal(1, "second back-to-back write errored");

    if (dut.memory[0] !== 32'h1111_1111 || dut.memory[1] !== 32'h2222_2222)
      $fatal(1, "back-to-back writes lost: %08x %08x", dut.memory[0], dut.memory[1]);

    hresetn = 0;
    @(posedge hclk); #1;
    if (dut.memory[0] !== 0 || dut.memory[1] !== 0)
      $fatal(1, "reset did not clear model memory");

    $display("PASS: AHB slave back-to-back writes and reset");
    $finish;
  end
endmodule
