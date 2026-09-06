module tb;
  parameter [31:0] INIT = 0;
  reg clk=0;
  always #5 clk=~clk;
  reg resetn=0, selected=1, advance=1;
  reg [31:0] address=0, data=0;
  reg [1:0] trans=0;
  reg write=0;
  reg [2:0] size=2;
  wire [31:0] result;
  wire readyout, response;
  wire ready=readyout && advance;
  agamemnon_ahb_ram #(.INITIAL_WORD(INIT)) dut(
    .HCLK(clk),.HRESETn(resetn),.HSEL(selected),.HREADY(ready),
    .HADDR(address),.HWDATA(data),.HTRANS(trans),.HWRITE(write),.HSIZE(size),
    .HRDATA(result),.HREADYOUT(readyout),.HRESP(response));
  integer word_index, lane;
  reg [31:0] expected[0:511];
  task access;
    input [31:0] addr, value;
    input wr, error;
    input [2:0] access_size;
    input [31:0] expect_read;
    begin
      @(negedge clk);address=addr;trans=2;write=wr;size=access_size;data=~value;
      @(posedge clk);#1;
      if (readyout !== 0 || response !== error) $fatal(1,"missing wait/error phase");
      @(negedge clk);trans=0;address=32'h12345678;data=value;
      @(posedge clk);#1;
      if (readyout !== 1 || response !== error) $fatal(1,"missing completion phase");
      if (!wr && !error && result !== expect_read) $fatal(1,"read %h got %h expected %h",addr,result,expect_read);
      @(posedge clk);#1;
      if (response !== 0) $fatal(1,"error remained after completion");
    end
  endtask
  initial begin
    repeat(2) @(posedge clk);
    @(negedge clk);resetn=1;
    for(word_index=0;word_index<512;word_index=word_index+1) begin
      expected[word_index]=INIT;
      access(32'h60000000+word_index*4,0,0,0,2,INIT);
    end
    // Independent addresses with distinct full-width values, then reverse readback.
    for(word_index=0;word_index<512;word_index=word_index+1) begin
      expected[word_index]=32'h9e3779b9*word_index ^ 32'ha55ac33c;
      access(32'h60000000+word_index*4,expected[word_index],1,0,2,0);
    end
    for(word_index=511;word_index>=0;word_index=word_index-1)
      access(32'h60000000+word_index*4,0,0,0,2,expected[word_index]);
    for(lane=0;lane<32;lane=lane+1) begin
      access(32'h60000000,32'b1<<lane,1,0,2,0);
      access(32'h60000000,0,0,0,2,32'b1<<lane);
      access(32'h600007fc,~(32'b1<<lane),1,0,2,0);
      access(32'h600007fc,0,0,0,2,~(32'b1<<lane));
    end
    // Reject unaligned, subword, oversized and out-of-window transfers.
    access(32'h60000001,32'hffffffff,1,1,2,0);
    access(32'h60000000,32'hffffffff,1,1,0,0);
    access(32'h60000000,32'hffffffff,1,1,1,0);
    access(32'h60000000,32'hffffffff,1,1,3,0);
    access(32'h60000800,32'hffffffff,1,1,2,0);
    access(32'h5ffffffc,32'hffffffff,1,1,2,0);
    access(32'h60000000,0,0,0,2,32'h80000000);
    // Adjacent transfers overlap the first data phase and second address phase.
    @(negedge clk);address=32'h60000008;trans=2;write=1;size=2;data=32'hbad;
    @(posedge clk);#1;
    @(negedge clk);address=32'h6000000c;data=32'h12345678;
    @(posedge clk);#1;
    if (!readyout) $fatal(1,"first back-to-back transfer not ready");
    @(posedge clk);#1;
    if (readyout) $fatal(1,"second back-to-back transfer not captured");
    @(negedge clk);trans=0;data=32'h89abcdef;
    @(posedge clk);#1;
    @(posedge clk);#1;
    access(32'h60000008,0,0,0,2,32'h12345678);
    access(32'h6000000c,0,0,0,2,32'h89abcdef);
    // Global stalls must not retire a pending write or accept another address.
    @(negedge clk);address=32'h60000008;trans=2;write=1;data=0;
    @(posedge clk);#1;
    @(negedge clk);advance=0;data=32'hfedcba98;trans=0;
    repeat(3) @(posedge clk);
    #1;if(dut.memory[2] !== 32'h12345678) $fatal(1,"write retired without global ready");
    @(negedge clk);advance=1;
    @(posedge clk);#1;
    access(32'h60000008,0,0,0,2,32'hfedcba98);
    // Reset cancels a pending write without erasing storage.
    @(negedge clk);address=32'h60000008;trans=2;write=1;data=0;
    @(posedge clk);#1;
    @(negedge clk);resetn=0;trans=0;
    @(posedge clk);#1;
    @(negedge clk);resetn=1;
    access(32'h60000008,0,0,0,2,32'hfedcba98);
    $display("PASS full-depth/full-word RAM, data phase, overlap, stalls, errors, reset");
    $finish;
  end
endmodule
