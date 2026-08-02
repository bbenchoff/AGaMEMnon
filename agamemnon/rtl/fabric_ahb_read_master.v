// Reset-idle, single-transfer, read-only AHB-Lite master core.
//
// This module is vendor-independent protocol logic. It does not instantiate
// the recovered AG32 hard-boundary primitives; a later wrapper may connect its
// signals after the request payload BEL gap is closed. Writes are deliberately
// impossible and every stalled transfer ends in a bounded timeout.
module agamemnon_fabric_ahb_read_master #(
  parameter integer TIMEOUT_CYCLES = 16
) (
  input  wire        HCLK,
  input  wire        HRESETn,
  input  wire        start,
  input  wire [31:0] address,

  output reg         busy,
  output reg         done,
  output reg         error,
  output reg         timed_out,
  output reg  [31:0] read_data,

  output reg         HSEL,
  output reg         HREADY,
  output reg  [1:0]  HTRANS,
  output wire [2:0]  HSIZE,
  output wire [2:0]  HBURST,
  output wire        HWRITE,
  output reg  [31:0] HADDR,
  output wire [31:0] HWDATA,
  input  wire        HREADYOUT,
  input  wire        HRESP,
  input  wire [31:0] HRDATA
);
  localparam [1:0] STATE_IDLE = 2'd0;
  localparam [1:0] STATE_ADDR = 2'd1;
  localparam [1:0] STATE_DATA = 2'd2;

  reg [1:0] state;
  integer wait_count;

  assign HSIZE = 3'd2;
  assign HBURST = 3'd0;
  assign HWRITE = 1'b0;
  assign HWDATA = 32'b0;

  always @* begin
    HSEL = 1'b0;
    HREADY = 1'b1;
    HTRANS = 2'b00;
    if (state == STATE_ADDR) begin
      HSEL = 1'b1;
      HTRANS = 2'b10; // NONSEQ
    end else if (state == STATE_DATA) begin
      // Feed the slave's completion into the global pipeline-ready input while
      // presenting IDLE as the next address phase.
      HREADY = HREADYOUT;
    end
  end

  always @(posedge HCLK or negedge HRESETn) begin
    if (!HRESETn) begin
      state <= STATE_IDLE;
      busy <= 1'b0;
      done <= 1'b0;
      error <= 1'b0;
      timed_out <= 1'b0;
      read_data <= 32'b0;
      HADDR <= 32'b0;
      wait_count <= 0;
    end else begin
      done <= 1'b0;
      if (state == STATE_IDLE) begin
        busy <= 1'b0;
        if (start) begin
          HADDR <= address;
          busy <= 1'b1;
          error <= 1'b0;
          timed_out <= 1'b0;
          wait_count <= 0;
          state <= STATE_ADDR;
        end
      end else if (state == STATE_ADDR) begin
        // The address/control phase is accepted on this edge. The following
        // cycle is the response data phase.
        state <= STATE_DATA;
      end else begin
        if (HREADYOUT) begin
          read_data <= HRDATA;
          error <= HRESP;
          timed_out <= 1'b0;
          busy <= 1'b0;
          done <= 1'b1;
          state <= STATE_IDLE;
        end else if (wait_count + 1 >= TIMEOUT_CYCLES) begin
          error <= 1'b1;
          timed_out <= 1'b1;
          busy <= 1'b0;
          done <= 1'b1;
          state <= STATE_IDLE;
        end else begin
          wait_count <= wait_count + 1;
        end
      end
    end
  end
endmodule
