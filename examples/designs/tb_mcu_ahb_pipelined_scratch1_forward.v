`timescale 1ns/1ps

module tb_mcu_ahb_pipelined_scratch1_forward;
  reg hclk = 0;
  always #5 hclk = ~hclk;
  reg htrans1 = 0, hwrite = 0, hwdata0 = 0, reset_request = 1;
  wire hreadyout, hresp, hrdata0;

  agamemnon_ahb_pipelined_scratch1_forward_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .hwdata0(hwdata0), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata0(hrdata0));

  task tick;
    begin @(posedge hclk); #1; end
  endtask

  initial begin
    tick(); tick(); reset_request = 0;
    @(negedge hclk); htrans1 = 1; hwrite = 1; tick(); // write address
    @(negedge hclk); hwrite = 0; hwdata0 = 1; tick(); // data + read address
    if (hrdata0 !== 1 || hreadyout !== 1 || hresp !== 0)
      $fatal(1, "write/read forwarding failed");
    @(negedge hclk); htrans1 = 0; tick();             // retire to scratch
    if (hrdata0 !== 1) $fatal(1, "forwarded value did not retire");

    // Two consecutive writes followed immediately by a read: the second
    // captured value must win even while the first is retiring to scratch.
    @(negedge hclk); htrans1 = 1; hwrite = 1; tick();
    @(negedge hclk); hwrite = 1; hwdata0 = 0; tick();
    @(negedge hclk); hwrite = 0; hwdata0 = 1; tick();
    if (hrdata0 !== 1) $fatal(1, "back-to-back forwarding lost newest write");
    @(negedge hclk); htrans1 = 0; tick();
    if (hrdata0 !== 1) $fatal(1, "back-to-back value did not retire");

    $display("PASS: posted scratch same-address forwarding");
    $finish;
  end
endmodule
