`timescale 1ns/1ps
module tb_mcu_ahb_w1c_status1;
  reg hclk = 0;
  reg htrans1 = 0, hwrite = 0, haddr2 = 0, haddr3 = 0;
  reg hwdata0 = 0, hwdata1 = 0;
  wire [7:0] hrdata;
  agamemnon_ahb_w1c_status1_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3),
    .hwdata0(hwdata0), .hwdata1(hwdata1), .hrdata(hrdata));
  always #5 hclk = !hclk;

  task write_c(input [1:0] value);
    begin
      @(negedge hclk);
      htrans1 = 1; hwrite = 1; haddr3 = 1; haddr2 = 1;
      @(negedge hclk);
      htrans1 = 0; hwrite = 0; hwdata1 = value[1]; hwdata0 = value[0];
      @(negedge hclk);
      hwdata1 = 0; hwdata0 = 0;
      repeat (2) @(negedge hclk);
    end
  endtask

  initial begin
    repeat (2) @(negedge hclk);
    haddr3 = 1; haddr2 = 1;
    if (hrdata !== 0) $fatal(1, "status reset %0h", hrdata);
    write_c(2'b10);
    if (hrdata !== 1) $fatal(1, "set %0h", hrdata);
    write_c(2'b00);
    if (hrdata !== 1) $fatal(1, "hold %0h", hrdata);
    write_c(2'b01);
    if (hrdata !== 0) $fatal(1, "clear %0h", hrdata);
    write_c(2'b10);
    if (hrdata !== 1) $fatal(1, "re-arm %0h", hrdata);
    write_c(2'b11);
    if (hrdata !== 1) $fatal(1, "set priority %0h", hrdata);
    haddr3 = 0; haddr2 = 0; @(negedge hclk);
    if (hrdata !== 0) $fatal(1, "offset0 %0h", hrdata);
    haddr3 = 0; haddr2 = 1; @(negedge hclk);
    if (hrdata !== 0) $fatal(1, "offset4 %0h", hrdata);
    haddr3 = 1; haddr2 = 0; @(negedge hclk);
    if (hrdata !== 0) $fatal(1, "offset8 %0h", hrdata);
    $display("PASS: standalone one-bit W1C status register");
    $finish;
  end
endmodule
