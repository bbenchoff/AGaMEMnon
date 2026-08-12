// Register-backed 8-N-1 soft UART for the AG32 External AHB window.
//
// Register map (word-aligned SINGLE transfers only):
//   +0x0 TXDATA  write low byte to launch; reads return zero
//   +0x4 RXDATA  read low byte and acknowledge receive state
//   +0x8 STATUS  bit0 TX busy, bit1 RX valid, bit2 framing, bit3 overrun
//   +0xc DIVISOR read the fixed clocks-per-bit parameter
module agamemnon_ahb_soft_uart #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter integer CLOCKS_PER_BIT = 87,
  parameter integer WAIT_STATES = 1
) (
  input  wire        HCLK,
  input  wire        HRESETn,
  input  wire        HSEL,
  input  wire [31:0] HADDR,
  input  wire [1:0]  HTRANS,
  input  wire        HWRITE,
  input  wire [2:0]  HSIZE,
  input  wire [2:0]  HBURST,
  input  wire [31:0] HWDATA,
  input  wire        HREADY,
  output reg  [31:0] HRDATA,
  output wire        HREADYOUT,
  output wire        HRESP,
  input  wire        RXD,
  output wire        TXD,
  output wire        IRQ
);
  localparam [3:0] REG_TXDATA  = 4'h0;
  localparam [3:0] REG_RXDATA  = 4'h4;
  localparam [3:0] REG_STATUS  = 4'h8;
  localparam [3:0] REG_DIVISOR = 4'hc;
  localparam integer HALF_BIT = CLOCKS_PER_BIT / 2;

  reg active;
  reg transfer_in_range;
  reg [3:0] transfer_offset;
  reg transfer_write;
  reg [2:0] transfer_size;
  reg [2:0] transfer_burst;
  reg [4:0] wait_count;

  reg [1:0] rx_sync;
  reg tx_busy;
  reg [31:0] tx_divider;
  reg [3:0] tx_bit;
  reg [9:0] tx_frame;

  reg rx_busy;
  reg [31:0] rx_divider;
  reg [3:0] rx_bit;
  reg [7:0] rx_shift;
  reg [7:0] rx_data;
  reg rx_valid;
  reg rx_framing;
  reg rx_overrun;

  wire [3:0] register_offset = {transfer_offset[3:2], 2'b00};
  wire known_register = register_offset == REG_TXDATA ||
                        register_offset == REG_RXDATA ||
                        register_offset == REG_STATUS ||
                        register_offset == REG_DIVISOR;
  wire writable_register = register_offset == REG_TXDATA && !tx_busy;
  wire valid = transfer_in_range && transfer_size == 3'd2 &&
               transfer_offset[1:0] == 2'b00 &&
               transfer_burst == 3'b000 && known_register &&
               (!transfer_write || writable_register);
  wire complete = active && wait_count == 0;

  assign HREADYOUT = !active || wait_count == 0;
  assign HRESP = complete && !valid;
  assign TXD = tx_busy ? tx_frame[0] : 1'b1;
  assign IRQ = rx_valid;

  always @* begin
    HRDATA = 32'b0;
    if (complete && valid && !transfer_write) begin
      case (register_offset)
        REG_RXDATA:  HRDATA = {24'b0, rx_data};
        REG_STATUS:  HRDATA = {28'b0, rx_overrun, rx_framing,
                               rx_valid, tx_busy};
        REG_DIVISOR: HRDATA = CLOCKS_PER_BIT;
        default:     HRDATA = 32'b0;
      endcase
    end
  end

  always @(posedge HCLK) begin
    if (!HRESETn) begin
      active <= 0;
      transfer_in_range <= 0;
      transfer_offset <= 0;
      transfer_write <= 0;
      transfer_size <= 0;
      transfer_burst <= 0;
      wait_count <= 0;
      rx_sync <= 2'b11;
      tx_busy <= 0;
      tx_divider <= 0;
      tx_bit <= 0;
      tx_frame <= 10'h3ff;
      rx_busy <= 0;
      rx_divider <= 0;
      rx_bit <= 0;
      rx_shift <= 0;
      rx_data <= 0;
      rx_valid <= 0;
      rx_framing <= 0;
      rx_overrun <= 0;
    end else begin
      rx_sync <= {rx_sync[0], RXD};

      if (tx_busy) begin
        if (tx_divider == CLOCKS_PER_BIT - 1) begin
          tx_divider <= 0;
          if (tx_bit == 9) begin
            tx_busy <= 0;
            tx_frame <= 10'h3ff;
          end else begin
            tx_frame <= {1'b1, tx_frame[9:1]};
            tx_bit <= tx_bit + 1'b1;
          end
        end else begin
          tx_divider <= tx_divider + 1'b1;
        end
      end

      if (!rx_busy) begin
        if (!rx_sync[1]) begin
          rx_busy <= 1;
          rx_divider <= HALF_BIT - 1;
          rx_bit <= 0;
        end
      end else if (rx_divider != 0) begin
        rx_divider <= rx_divider - 1'b1;
      end else if (rx_bit == 0) begin
        if (rx_sync[1]) begin
          rx_busy <= 0;
        end else begin
          rx_bit <= 1;
          rx_divider <= CLOCKS_PER_BIT - 1;
        end
      end else if (rx_bit <= 8) begin
        rx_shift[rx_bit - 1'b1] <= rx_sync[1];
        rx_bit <= rx_bit + 1'b1;
        rx_divider <= CLOCKS_PER_BIT - 1;
      end else begin
        rx_busy <= 0;
        if (rx_sync[1]) begin
          if (rx_valid)
            rx_overrun <= 1;
          rx_data <= rx_shift;
          rx_valid <= 1;
        end else begin
          rx_framing <= 1;
        end
      end

      if (active && wait_count != 0)
        wait_count <= wait_count - 1'b1;

      if (complete && HREADY) begin
        if (valid && transfer_write && register_offset == REG_TXDATA) begin
          tx_frame <= {1'b1, HWDATA[7:0], 1'b0};
          tx_divider <= 0;
          tx_bit <= 0;
          tx_busy <= 1;
        end
        if (valid && !transfer_write && register_offset == REG_RXDATA) begin
          rx_valid <= 0;
          rx_framing <= 0;
          rx_overrun <= 0;
        end
        active <= 0;
      end

      if (HREADY && HREADYOUT && HSEL && HTRANS[1]) begin
        active <= 1;
        transfer_in_range <= HADDR[31:4] == BASE_ADDR[31:4];
        transfer_offset <= HADDR[3:0];
        transfer_write <= HWRITE;
        transfer_size <= HSIZE;
        transfer_burst <= HBURST;
        wait_count <= WAIT_STATES;
      end
    end
  end
endmodule


// Hard-port wrapper for the soft-UART alternative. The UART replaces the
// four-register bank at the same 16-byte window; it does not require an
// additional HADDR bit or claim simultaneous composition with that bank.
module agamemnon_mcu_ahb_soft_uart #(
  parameter [31:0] BASE_ADDR = 32'h6000_0000,
  parameter integer CLOCKS_PER_BIT = 87,
  parameter integer WAIT_STATES = 1
) (
  input  wire RXD,
  output wire TXD,
  output wire IRQ
);
  wire hclk, hresetn, hready, hwrite;
  wire [1:0] htrans;
  wire [2:0] hsize, hburst;
  wire [31:0] haddr, hwdata, hrdata;
  wire hreadyout, hresp;
  wire [31:0] haddr_seen = (haddr & 32'h0000_000f) |
                           (BASE_ADDR & 32'hffff_fff0);
  wire [31:0] hwdata_seen = hwdata & 32'h0000_00ff;

  agamemnon_mcu_ahb_port port_i(
    .HCLK(hclk), .HRESETn(hresetn), .HREADY(hready), .HTRANS(htrans),
    .HSIZE(hsize), .HBURST(hburst), .HWRITE(hwrite), .HADDR(haddr),
    .HWDATA(hwdata), .HREADYOUT(hreadyout), .HRESP(hresp), .HRDATA(hrdata));

  agamemnon_ahb_soft_uart #(
    .BASE_ADDR(BASE_ADDR), .CLOCKS_PER_BIT(CLOCKS_PER_BIT),
    .WAIT_STATES(WAIT_STATES)
  ) uart_i (
    .HCLK(hclk), .HRESETn(hresetn), .HSEL(1'b1), .HADDR(haddr_seen),
    .HTRANS(htrans), .HWRITE(hwrite), .HSIZE(hsize), .HBURST(hburst),
    .HWDATA(hwdata_seen), .HREADY(hready), .HRDATA(hrdata),
    .HREADYOUT(hreadyout), .HRESP(hresp), .RXD(RXD), .TXD(TXD), .IRQ(IRQ));
endmodule
