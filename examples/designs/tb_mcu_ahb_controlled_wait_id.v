`timescale 1ns/1ps
module tb_mcu_ahb_controlled_wait_id;
  reg hclk=0; always #5 hclk=~hclk;
  reg htrans1=0, reset_request=1;
  wire hreadyout, hresp;
  wire [7:0] hrdata;
  integer waits, transfer;

  agamemnon_ahb_controlled_wait_id_core dut(
    .hclk(hclk), .htrans1(htrans1), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata));

  task tick; begin @(posedge hclk); #1; end endtask
  task read_transfer; begin
    @(negedge hclk); htrans1=1; tick(); waits=0;
    @(negedge hclk);
    while (!hreadyout) begin waits=waits+1; tick(); @(negedge hclk); end
    if (waits != 1) $fatal(1,"wait count %0d",waits);
    htrans1=0; tick();
    if (hrdata !== 8'h4d || hresp) $fatal(1,"response %02x/%0d",hrdata,hresp);
  end endtask

  initial begin
    tick(); tick();
    if (!hreadyout || hrdata !== 8'h4d) $fatal(1,"reset response");
    reset_request=0; repeat(2) tick();
    for (transfer=0; transfer<16; transfer=transfer+1) read_transfer();
    reset_request=1; tick();
    if (!hreadyout) $fatal(1,"reset did not force ready");
    $display("PASS: controlled one-wait ID endpoint");
    $finish;
  end
endmodule
