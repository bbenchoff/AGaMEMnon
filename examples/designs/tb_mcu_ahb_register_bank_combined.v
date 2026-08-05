`timescale 1ns/1ps
module tb_mcu_ahb_register_bank_combined;
  reg hclk=0; always #5 hclk=~hclk;
  reg htrans1=0, hwrite=0, haddr2=0, haddr3=0, reset_request=1;
  reg [7:0] hwdata=0;
  wire hreadyout, hresp;
  wire [7:0] hrdata;
  agamemnon_ahb_register_bank_combined_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .haddr2(haddr2), .haddr3(haddr3), .hwdata(hwdata),
    .reset_request(reset_request), .hreadyout(hreadyout),
    .hresp(hresp), .hrdata(hrdata));

  task tick; begin @(posedge hclk); #1; end endtask
  task address(input [1:0] word); begin
    @(negedge hclk); haddr3=word[1]; haddr2=word[0]; tick();
  end endtask
  task write_word(input [1:0] word, input [7:0] value); begin
    @(negedge hclk); htrans1=1; hwrite=1;
    haddr3=word[1]; haddr2=word[0]; tick();
    @(negedge hclk); htrans1=0; hwrite=0; hwdata=value; tick();
    repeat (4) tick();
  end endtask

  integer value;
  reg [2:0] count0, count1;
  initial begin
    tick(); tick(); reset_request=0;
    address(2'b00); if (hrdata !== 8'h4d) $fatal(1,"ID %02x",hrdata);
    for (value=0; value<256; value=value+1) begin
      write_word(2'b01,value[7:0]);
      address(2'b01);
      if (hrdata !== value[7:0]) $fatal(1,"scratch %0d -> %02x",value,hrdata);
    end
    write_word(2'b00,8'h00);
    address(2'b00); if (hrdata !== 8'h4d) $fatal(1,"ID changed");
    address(2'b01); if (hrdata !== 8'hff) $fatal(1,"scratch changed");

    address(2'b10); count0=hrdata[2:0]; tick(); count1=hrdata[2:0];
    if (count1 !== ((count0+1'b1)&3'h7))
      $fatal(1,"counter %0d %0d",count0,count1);

    write_word(2'b11,8'h02);
    address(2'b11); if (hrdata !== 8'h01) $fatal(1,"set %02x",hrdata);
    write_word(2'b11,8'h00);
    address(2'b11); if (hrdata !== 8'h01) $fatal(1,"hold %02x",hrdata);
    write_word(2'b11,8'h01);
    address(2'b11); if (hrdata !== 8'h00) $fatal(1,"clear %02x",hrdata);
    write_word(2'b11,8'h02);
    write_word(2'b11,8'h03);
    address(2'b11); if (hrdata !== 8'h01) $fatal(1,"priority %02x",hrdata);
    address(2'b01); if (hrdata !== 8'hff) $fatal(1,"status corrupted scratch");
    if (!hreadyout || hresp) $fatal(1,"constant response");
    $display("PASS: combined byte ID/scratch/counter/W1C bank");
    $finish;
  end
endmodule
