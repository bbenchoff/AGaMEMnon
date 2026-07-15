// Isolate the serial-mux receiver: latch PIN_16 high after one valid 9600-8N1
// frame on PIN_10.  Logic is intentionally identical to the demo receiver.
(* top *) module top #(parameter integer CLK_HZ = 25_000_000, RX_BAUD = 24414)(
    input wire clock, input wire rx, output wire seen
);
    localparam integer CLK_DIV = CLK_HZ / RX_BAUD;
    wire [7:0] data;
    wire strobe, synced;
    wire [1:0] debug_state;
    wire rx_fabric;
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) rx_buffer(
        .I({3'b000, rx}), .Q(rx_fabric));
    probe_uart_rx #(.CLK_DIV(CLK_DIV)) receiver(
        .clock(clock), .rx(rx_fabric), .data(data), .strobe(strobe), .synced(synced),
        .debug_state(debug_state));
    reg seen_byte;
    initial seen_byte = 1'b0;
    always @(posedge clock)
        if (strobe) seen_byte <= ~seen_byte;
    assign seen = seen_byte;
endmodule

module probe_uart_rx #(parameter integer CLK_DIV = 2604)(
    input wire clock, input wire rx, output reg [7:0] data, output reg strobe,
    output wire synced, output wire [1:0] debug_state
);
    // Diagnostic direct-pad mode: isolates the characterized input route from
    // the still-under-test registered-input Q fanout.
    wire rxs = rx;
    assign synced = rxs;
    localparam [1:0] S_IDLE=0, S_START=1, S_DATA=2, S_STOP=3;
    // Configuration clears this binary state to S_IDLE.  Do not let Yosys
    // recode it to one-hot: all-zero is not a valid one-hot state on silicon.
    (* fsm_encoding = "none" *) reg [1:0] state;
    assign debug_state = state;
    reg [11:0] cnt;
    localparam integer DIV_SHIFT = $clog2(CLK_DIV);
    reg [2:0] bitidx;
    reg [7:0] shift;
    always @(posedge clock) begin
        strobe <= 1'b0;
        case (state)
            S_IDLE: if (!rxs) begin state <= S_START; cnt <= 0; end
            S_START: if (cnt[DIV_SHIFT-1]) begin
                cnt <= 0;
                if (!rxs) begin state <= S_DATA; bitidx <= 0; end
                else state <= S_IDLE;
            end else cnt <= cnt + 1'b1;
            S_DATA: if (cnt[DIV_SHIFT]) begin
                cnt <= 0; shift <= {rxs, shift[7:1]};
                if (bitidx == 7) state <= S_STOP;
                else bitidx <= bitidx + 1'b1;
            end else cnt <= cnt + 1'b1;
            default: if (cnt[DIV_SHIFT]) begin
                state <= S_IDLE;
                if (rxs) begin data <= shift; strobe <= 1'b1; end
            end else cnt <= cnt + 1'b1;
        endcase
    end
endmodule
