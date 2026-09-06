// Synchronous inferred RAM with a word-transfer AHB-Lite interface.
// One wait cycle separates address capture, synchronous read, and retirement.
// HWDATA is captured during that wait cycle, never in the address phase.
// Hardware qualification is separate from the protocol simulation tests.
module agamemnon_ahb_ram #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter integer ADDRESS_BITS = 9,
  parameter [31:0] INITIAL_WORD = 0
) (
  input wire HCLK, HRESETn, HSEL, HREADY,
  input wire [31:0] HADDR, HWDATA,
  input wire [1:0] HTRANS,
  input wire HWRITE,
  input wire [2:0] HSIZE,
  output wire [31:0] HRDATA,
  output wire HREADYOUT, HRESP
);
  localparam integer WORDS = 1 << ADDRESS_BITS;
  (* ram_style="block" *) reg [31:0] memory [0:WORDS-1];
  integer index;
  initial begin
    for (index=0; index<WORDS; index=index+1) memory[index] = INITIAL_WORD;
  end
  reg active = 0, wait_pending = 0, transfer_write = 0, transfer_valid = 0;
  reg [ADDRESS_BITS-1:0] transfer_address = 0;
  reg [31:0] write_data_pipe;
  reg [31:0] read_data;
  wire complete = active && !wait_pending;
  wire [31:0] offset = HADDR - BASE_ADDR;
  wire address_valid = HADDR >= BASE_ADDR && offset < WORDS * 4 && HADDR[1:0] == 0;
  assign HREADYOUT = !active || !wait_pending;
  // Invalid transfers get the required low-ready error cycle followed by
  // the high-ready error cycle; neither cycle may change the memory.
  assign HRESP = active && !transfer_valid;
  assign HRDATA = active && transfer_valid && !transfer_write ? read_data : 0;

  always @(posedge HCLK) begin
    write_data_pipe <= HWDATA;
    read_data <= memory[transfer_address];
    if (HRESETn && complete && HREADY && transfer_valid && transfer_write)
      memory[transfer_address] <= write_data_pipe;
  end
  always @(posedge HCLK) begin
    if (!HRESETn) begin
      active <= 0;
      wait_pending <= 0;
      transfer_write <= 0;
      transfer_valid <= 0;
      transfer_address <= 0;
    end else begin
      if (active && wait_pending) wait_pending <= 0;
      if (complete && HREADY) active <= 0;
      if (HREADY && HREADYOUT) begin
        active <= HSEL && HTRANS[1];
        if (HSEL && HTRANS[1]) begin
          transfer_address <= offset[ADDRESS_BITS+1:2];
          transfer_write <= HWRITE;
          transfer_valid <= address_valid && HSIZE == 3'd2;
          wait_pending <= 1;
        end
      end
    end
  end
endmodule

// Full-width hard-port binding. No HADDR or HWDATA lanes are silently tied off.
module agamemnon_mcu_ahb_ram;
  wire clk, resetn, ready, write;
  wire [31:0] address, data, result;
  wire [1:0] trans;
  wire [2:0] size, burst;
  wire readyout, response;
  agamemnon_mcu_ahb_port port_i(
    .HCLK(clk), .HRESETn(resetn), .HREADY(ready), .HTRANS(trans),
    .HSIZE(size), .HBURST(burst), .HWRITE(write), .HADDR(address),
    .HWDATA(data), .HREADYOUT(readyout), .HRESP(response), .HRDATA(result));
  agamemnon_ahb_ram ram_i(
    .HCLK(clk), .HRESETn(resetn), .HSEL(1'b1), .HREADY(ready),
    .HADDR(address), .HWDATA(data), .HTRANS(trans), .HWRITE(write),
    .HSIZE(size), .HRDATA(result), .HREADYOUT(readyout), .HRESP(response));
endmodule
