`timescale 1ns/1ps

module tb_mcu_ahb_pipelined_scratch1;
  reg hclk = 0;
  always #5 hclk = ~hclk;

  reg htrans1 = 0;
  reg hwrite = 0;
  reg hwdata0 = 0;
  reg reset_request = 1;
  wire hreadyout, hresp, hrdata0;

  agamemnon_ahb_pipelined_scratch1_core dut(
    .hclk(hclk), .htrans1(htrans1), .hwrite(hwrite),
    .hwdata0(hwdata0), .reset_request(reset_request),
    .hreadyout(hreadyout), .hresp(hresp), .hrdata0(hrdata0));

  task idle_edge;
    begin
      @(negedge hclk);
      htrans1 = 0;
      hwrite = 0;
      @(posedge hclk);
      #1;
    end
  endtask

  task write_one;
    input value;
    begin
      @(negedge hclk);
      htrans1 = 1;
      hwrite = 1;
      @(posedge hclk); // address accepted; posted completion stays ready
      #1;
      if (hreadyout !== 1)
        $fatal(1, "posted write deasserted HREADYOUT");
      @(negedge hclk);
      htrans1 = 0;
      hwdata0 = value;
      @(posedge hclk); // data captured
      #1;
      @(posedge hclk); // captured data commits internally
      #1;
    end
  endtask

  task read_expect;
    input expected;
    begin
      @(negedge hclk);
      htrans1 = 1;
      hwrite = 0;
      @(posedge hclk); // address accepted; zero-wait read data phase
      #1;
      if (hreadyout !== 1 || hrdata0 !== expected)
        $fatal(1, "read mismatch expected=%0d got=%0d ready=%0d",
               expected, hrdata0, hreadyout);
      @(negedge hclk);
      htrans1 = 0;
      @(posedge hclk);
      #1;
    end
  endtask

  initial begin
    repeat (2) @(posedge hclk);
    reset_request = 0;
    idle_edge();
    if (hresp !== 0)
      $fatal(1, "minimal oracle must be OKAY-only");

    read_expect(0);
    write_one(1);
    read_expect(1);

    // Write followed immediately by a read address phase.  At the read data
    // edge the posted write has committed from its registered data stage.
    @(negedge hclk);
    htrans1 = 1;
    hwrite = 1;
    @(posedge hclk);
    #1;
    if (hreadyout !== 1) $fatal(1, "posted write/read stalled");
    @(negedge hclk);
    hwrite = 0;       // next address is a read
    hwdata0 = 0;      // current write data phase
    @(posedge hclk);  // write data captured; read address accepted
    #1;
    @(posedge hclk);  // posted write commits; read data phase observes it
    #1;
    if (hrdata0 !== 0)
      $fatal(1, "immediate write/read did not return captured write data");
    @(negedge hclk);
    htrans1 = 0;
    @(posedge hclk);

    // Two consecutive write address phases with consecutive data phases.
    @(negedge hclk);
    htrans1 = 1;
    hwrite = 1;
    @(posedge hclk);
    @(negedge hclk);
    htrans1 = 1;
    hwrite = 1;
    hwdata0 = 1;
    @(posedge hclk); // data0 captured, address1 accepted
    #1;
    if (hreadyout !== 1) $fatal(1, "back-to-back posted writes stalled");
    @(negedge hclk);
    htrans1 = 0;
    hwdata0 = 0;
    @(posedge hclk); // data1 captured; data0 commits
    #1;
    @(posedge hclk); // data1 commits
    #1;
    read_expect(0);

    $display("PASS: one-bit pipelined AHB scratch timing");
    $finish;
  end
endmodule
