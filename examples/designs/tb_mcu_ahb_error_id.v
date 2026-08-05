`timescale 1ns/1ps
module tb_mcu_ahb_error_id;
  reg hclk = 0; always #5 hclk = ~hclk;
  reg reset_request = 1, htrans1 = 0, haddr2 = 0;
  wire hreadyout, hresp;
  wire [7:0] hrdata;

  agamemnon_ahb_error_id_core dut(
    .hclk(hclk), .reset_request(reset_request),
    .htrans1(htrans1), .haddr2(haddr2),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata));

  initial begin
    @(posedge hclk); #1;
    if (!hreadyout || hresp || hrdata !== 8'h4d)
      $fatal(1, "idle response");
    reset_request = 0;
    @(negedge hclk); htrans1 = 1; haddr2 = 0;
    @(posedge hclk); #1;
    if (!hreadyout || hresp || hrdata !== 8'h4d)
      $fatal(1, "offset-zero response");
    @(negedge hclk); htrans1 = 0;
    @(posedge hclk); #1;
    @(negedge hclk); htrans1 = 1; haddr2 = 1;
    @(posedge hclk); #1;
    if (hreadyout || !hresp || hrdata !== 8'h4f)
      $fatal(1, "first error cycle");
    @(posedge hclk); #1;
    if (!hreadyout || !hresp || hrdata !== 8'h4f)
      $fatal(1, "second error cycle");
    @(negedge hclk); htrans1 = 0; haddr2 = 0;
    @(posedge hclk); #1;
    if (!hreadyout || hresp)
      $fatal(1, "error did not retire");
    reset_request = 1; @(posedge hclk); #1;
    if (!hreadyout || hresp)
      $fatal(1, "reset response");
    $display("PASS: deterministic address-selected AHB error endpoint");
    $finish;
  end
endmodule
