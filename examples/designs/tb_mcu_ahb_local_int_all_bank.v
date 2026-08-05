`timescale 1ns/1ps
module tb_local_int_all_command_bank;
  reg hclk = 1'b0;
  reg htrans1 = 1'b0;
  reg hwrite = 1'b0;
  reg haddr2 = 1'b0;
  reg hwdata0 = 1'b0;
  reg hwdata1 = 1'b0;
  reg hwdata2 = 1'b0;
  reg hwdata3 = 1'b0;
  reg reset_request = 1'b1;
  wire hreadyout, hresp;
  wire [7:0] hrdata;
  wire [3:0] irq;
  integer lane;
  integer errors = 0;

  agamemnon_ahb_local_int_all_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite), .haddr2(haddr2),
    .hwdata0(hwdata0), .hwdata1(hwdata1),
    .hwdata2(hwdata2), .hwdata3(hwdata3),
    .reset_request(reset_request), .hreadyout(hreadyout), .hresp(hresp),
    .hrdata(hrdata), .irq(irq));

  always #5 hclk = ~hclk;

  task command;
    input [1:0] selected_lane;
    input [1:0] op;
    begin
      @(negedge hclk);
      htrans1 = 1'b1;
      hwrite = 1'b1;
      haddr2 = 1'b1;
      @(negedge hclk);
      htrans1 = 1'b0;
      hwrite = 1'b0;
      hwdata3 = selected_lane[1];
      hwdata2 = selected_lane[0];
      hwdata1 = op[1];
      hwdata0 = op[0];
      @(negedge hclk);
      hwdata3 = 1'b0;
      hwdata2 = 1'b0;
      hwdata1 = 1'b0;
      hwdata0 = 1'b0;
    end
  endtask

  task expect_irq;
    input [3:0] expected;
    begin
      #1;
      if (irq !== expected) begin
        $display("irq mismatch lane=%0d got=%b expected=%b", lane, irq, expected);
        errors = errors + 1;
      end
      if (hrdata !== 8'h00 || hreadyout !== 1'b1 || hresp !== 1'b0)
        errors = errors + 1;
    end
  endtask

  initial begin
    repeat (3) @(negedge hclk);
    reset_request = 1'b0;
    for (lane = 0; lane < 4; lane = lane + 1) begin
      command(lane[1:0], 2'b10);
      expect_irq(4'b0000);
      command(lane[1:0], 2'b11);
      expect_irq(4'b0001 << lane);
      command(lane[1:0], 2'b01);
      expect_irq(4'b0000);
      command(lane[1:0], 2'b11);
      expect_irq(4'b0001 << lane);
      command(lane[1:0], 2'b01);
      expect_irq(4'b0000);
      command(lane[1:0], 2'b00);
      command(lane[1:0], 2'b10);
      expect_irq(4'b0000);
      command(lane[1:0], 2'b11);
      expect_irq(4'b0001 << lane);
      command(lane[1:0], 2'b01);
      expect_irq(4'b0000);
    end
    reset_request = 1'b1;
    @(negedge hclk);
    expect_irq(4'b0000);
    if (errors == 0)
      $display("PASS all-four command bank");
    else
      $display("FAIL errors=%0d", errors);
    $finish(errors != 0);
  end
endmodule
