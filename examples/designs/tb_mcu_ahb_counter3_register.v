`timescale 1ns/1ps
module tb_mcu_ahb_counter3_register;
  reg hclk=0; always #5 hclk=~hclk;
  reg haddr2=0, haddr3=0;
  wire [7:0] hrdata;
  agamemnon_ahb_counter3_register_core dut(
    .hclk(hclk), .haddr2(haddr2), .haddr3(haddr3), .hrdata(hrdata));
  integer i;
  reg [7:0] prev;
  initial begin
    repeat (2) @(posedge hclk);
    haddr3=1; haddr2=0; @(posedge hclk); #1; prev=hrdata;
    for (i=0; i<16; i=i+1) begin
      @(posedge hclk); #1;
      if (hrdata !== ((prev + 1'b1) & 8'h07))
        $fatal(1, "counter step %0h -> %0h", prev, hrdata);
      prev=hrdata;
    end
    haddr2=1; @(posedge hclk); #1;
    if (hrdata !== 8'h00) $fatal(1, "offset C not zero");
    haddr3=0; haddr2=0; @(posedge hclk); #1;
    if (hrdata !== 8'h00) $fatal(1, "offset 0 not zero");
    $display("PASS: standalone three-bit counter register");
    $finish;
  end
endmodule
