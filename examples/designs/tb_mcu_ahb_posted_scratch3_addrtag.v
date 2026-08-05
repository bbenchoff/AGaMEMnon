`timescale 1ns/1ps
module tb_mcu_ahb_posted_scratch3_addrtag;
  reg hclk=0; always #5 hclk=~hclk;
  reg htrans1=0, hwrite=0, haddr2=0, reset_request=1;
  reg [2:0] hwdata=0;
  wire hreadyout, hresp;
  wire [2:0] hrdata;
  agamemnon_ahb_posted_scratch3_addrtag_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata(hwdata), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata));
  task tick; begin @(posedge hclk); #1; end endtask
  task write0(input [2:0] value); begin
    @(negedge hclk); htrans1=1; hwrite=1; haddr2=0; tick();
    @(negedge hclk); hwrite=0; hwdata=value; tick();
  end endtask
  integer value;
  initial begin
    tick(); tick(); reset_request=0;
    for (value=0; value<8; value=value+1) begin
      write0(value[2:0]);
      if (hrdata !== value[2:0]) $fatal(1, "value %0d", value);
    end
    @(negedge hclk); hwrite=1; haddr2=0; tick();
    @(negedge hclk); hwrite=0; haddr2=1; hwdata=0; tick();
    if (hrdata !== 0) $fatal(1, "cross-address forwarding");
    $display("PASS: three-bit posted scratch address-tag forwarding");
    $finish;
  end
endmodule
