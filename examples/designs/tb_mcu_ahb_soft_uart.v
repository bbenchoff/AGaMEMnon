`timescale 1ns/1ps

module tb_mcu_ahb_soft_uart;
  localparam [31:0] BASE = 32'h6000_0000;
  reg hclk = 0, hresetn = 0, hsel = 0, hwrite = 0;
  reg [31:0] haddr = 0, hwdata = 0;
  reg [1:0] htrans = 0;
  reg [2:0] hsize = 2, hburst = 0;
  wire [31:0] hrdata;
  wire hreadyout, hresp, txd, irq;
  wire hready = hreadyout;
  wire rxd = txd;
  always #5 hclk = ~hclk;

  agamemnon_ahb_soft_uart #(
    .BASE_ADDR(BASE), .CLOCKS_PER_BIT(8), .WAIT_STATES(1)
  ) dut (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(hsel), .HADDR(haddr),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .RXD(rxd), .TXD(txd), .IRQ(irq)
  );

  task automatic transfer(input [31:0] addr, input wr, input [2:0] size,
                          input [2:0] burst, input [31:0] wdata,
                          input expect_error, output reg [31:0] rdata);
    integer guard;
    begin
      @(negedge hclk);
      hsel = 1; haddr = addr; htrans = 2'b10; hwrite = wr;
      hsize = size; hburst = burst;
      @(posedge hclk); #1;
      if (hreadyout !== 1'b0) $fatal(1, "configured wait missing");
      @(negedge hclk);
      hsel = 0; htrans = 0; hwrite = 0; hburst = 0; hwdata = wdata;
      guard = 0;
      while (!hreadyout) begin
        @(posedge hclk); #1; guard = guard + 1;
        if (guard > 3) $fatal(1, "deadlock");
      end
      if (hresp !== expect_error)
        $fatal(1, "HRESP=%b expected=%b", hresp, expect_error);
      rdata = hrdata;
      @(posedge hclk); #1;
    end
  endtask

  task automatic wait_receive;
    integer guard;
    begin
      guard = 0;
      while (!irq) begin
        @(posedge hclk); #1; guard = guard + 1;
        if (guard > 120) $fatal(1, "receive timeout");
      end
    end
  endtask

  reg [31:0] data;
  integer pass;
  initial begin
    repeat (3) @(posedge hclk);
    hresetn = 1;

    transfer(BASE + 12, 0, 2, 0, 0, 0, data);
    if (data !== 8) $fatal(1, "divisor %08x", data);

    for (pass = 0; pass < 2; pass = pass + 1) begin
      transfer(BASE + 0, 1, 2, 0, 32'h55, 0, data);
      wait_receive();
      transfer(BASE + 8, 0, 2, 0, 0, 0, data);
      if (data[3:0] !== 4'b0010) $fatal(1, "status %08x", data);
      transfer(BASE + 4, 0, 2, 0, 0, 0, data);
      if (data !== 32'h55) $fatal(1, "loopback %08x", data);
      if (irq) $fatal(1, "RX acknowledge failed");
    end

    transfer(BASE + 0, 1, 2, 0, 32'ha6, 0, data);
    transfer(BASE + 0, 1, 2, 0, 32'h3c, 1, data);
    wait_receive();
    transfer(BASE + 4, 0, 2, 0, 0, 0, data);
    if (data !== 32'ha6) $fatal(1, "busy write disturbed frame %08x", data);

    transfer(BASE + 0, 1, 2, 3'b001, 32'hc3, 1, data);
    if (dut.tx_busy) $fatal(1, "burst write launched TX");
    transfer(BASE + 1, 0, 2, 0, 0, 1, data);
    transfer(BASE + 0, 0, 0, 0, 0, 1, data);

    $display("PASS: register-backed soft UART loopback and fail-closed protocol");
    $finish;
  end
endmodule
