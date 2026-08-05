`timescale 1ns/1ps
module tb_mcu_ahb_local_int0_bank;
  reg hclk=0; always #5 hclk=~hclk;
  reg htrans1=0, hwrite=0, haddr2=0, haddr3=0, reset_request=1;
  reg hwdata0=0, hwdata1=0;
  wire hreadyout, hresp, irq_pending, irq_mask, irq1;
  wire [7:0] hrdata;
  agamemnon_ahb_local_int1_bank_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3),
    .hwdata0(hwdata0), .hwdata1(hwdata1), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata(hrdata),
    .irq_pending(irq_pending), .irq_mask(irq_mask), .irq1(irq1));

  task tick; begin @(posedge hclk); #1; end endtask
  task command(input alias_c, input [1:0] value); begin
    @(negedge hclk); htrans1=1; hwrite=1;
    haddr3=alias_c; haddr2=1; tick();
    @(negedge hclk); htrans1=0; hwrite=0;
    hwdata1=value[1]; hwdata0=value[0]; tick();
    @(negedge hclk); hwdata1=0; hwdata0=0;
    repeat (3) tick();
  end endtask

  initial begin
    tick(); tick();
    if (irq_pending || irq_mask || irq1) $fatal(1,"reset state");
    reset_request=0; repeat (3) tick();
    command(1'b1,2'b10);
    if (!irq_pending || irq_mask || irq1) $fatal(1,"masked pending");
    command(1'b0,2'b11);
    if (!irq_pending || !irq_mask || !irq1) $fatal(1,"mask/set");
    command(1'b1,2'b01);
    if (irq_pending || !irq_mask || irq1) $fatal(1,"acknowledge");
    command(1'b0,2'b11);
    if (!irq1) $fatal(1,"re-arm");
    command(1'b1,2'b00);
    if (!irq_pending || irq_mask || irq1) $fatal(1,"mask hold");
    command(1'b0,2'b11);
    if (!irq_pending || !irq_mask || !irq1) $fatal(1,"unmask retained");
    reset_request=1; repeat (3) tick();
    if (irq_pending || irq_mask || irq1) $fatal(1,"reset clear");
    if (hrdata !== 8'h00) $fatal(1,"fail-closed read data");
    if (!hreadyout || hresp) $fatal(1,"constant response");
    $display("PASS: AHB-backed local_int0 composite commands");
    $finish;
  end
endmodule
