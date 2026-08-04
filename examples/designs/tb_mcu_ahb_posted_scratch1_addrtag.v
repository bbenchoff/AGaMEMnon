`timescale 1ns/1ps
module tb_mcu_ahb_posted_scratch1_addrtag;
  reg hclk=0; always #5 hclk=~hclk;
  reg htrans1=0, hwrite=0, haddr2=0, hwdata0=0, reset_request=1;
  wire hreadyout, hresp, hrdata0;
  agamemnon_ahb_posted_scratch1_addrtag_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata0(hwdata0), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata0(hrdata0));
  task tick; begin @(posedge hclk); #1; end endtask
  initial begin
    tick(); tick(); reset_request=0;
    // Write one to register 0 and read it immediately.
    @(negedge hclk); htrans1=1; hwrite=1; haddr2=0; tick();
    @(negedge hclk); hwrite=0; haddr2=0; hwdata0=1; tick();
    if (hrdata0 !== 1) $fatal(1, "same-address forwarding failed");
    // The same pending write must not leak into address 1.
    @(negedge hclk); hwrite=1; haddr2=0; tick();
    @(negedge hclk); hwrite=0; haddr2=1; hwdata0=0; tick();
    if (hrdata0 !== 0) $fatal(1, "cross-address misforward");
    @(negedge hclk); htrans1=0; haddr2=0; tick();
    if (hrdata0 !== 0) $fatal(1, "register zero did not retire");
    // A write to address 1 must be ignored.
    @(negedge hclk); htrans1=1; hwrite=1; haddr2=1; tick();
    @(negedge hclk); hwrite=0; haddr2=0; hwdata0=1; tick();
    @(negedge hclk); htrans1=0; tick();
    if (hrdata0 !== 0) $fatal(1, "address-one write modified register zero");
    $display("PASS: posted scratch address-tag forwarding");
    $finish;
  end
endmodule
