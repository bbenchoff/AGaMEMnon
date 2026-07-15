// Buffered three-input UART multiplexer.
//
// Three independent 8N1 receivers accept overlapping 9600-baud streams. Each
// channel has a one-byte elastic buffer; a round-robin arbiter drains them through one
// 115200-baud transmitter. With simultaneous A/B/C streams the output is
// ABCABC... without electrically combining the input wires.

`ifndef SERIAL_MUX_LIBRARY
(* top *)
`endif
module serial_mux #(
    parameter integer CLK_HZ = 25_000_000,
    parameter integer RX_BAUD = 9_600,
    parameter integer TX_BAUD = 115_200
) (
    input  wire clock,
    input  wire rx_a,
    input  wire rx_b,
    input  wire rx_c,
    output wire tx
);
    // One phase accumulator serves the transmitter and all receivers.  It is
    // deliberately expressed with the dedicated carry primitive: ordinary
    // LUT-routed terminal-count dividers can have the right average frequency
    // while dropping individual pulses on this fabric.  At 25 MHz the rounded
    // increment is 302, giving 115203.9 ticks/s and 9600.3 baud at 12x.
    localparam integer RX_TICKS = TX_BAUD / RX_BAUD;
    // The explicit 64-bit literal prevents Verilog's signed 32-bit constant
    // arithmetic from overflowing for 25 MHz / 115200 baud.
    localparam [63:0] NCO_NUMERATOR = TX_BAUD * 64'd65536 + CLK_HZ / 2;
    localparam integer NCO_INCREMENT = NCO_NUMERATOR / CLK_HZ;
    reg [15:0] baud_phase = 0;
    reg baud_tick = 0;
    wire [16:0] baud_next;
    wire [17:0] baud_carry;
    wire [16:0] baud_addend = NCO_INCREMENT;
    assign baud_carry[0] = 1'b0;
    genvar baud_bit;
    generate for (baud_bit = 0; baud_bit < 17; baud_bit = baud_bit + 1) begin: baud_nco
        AG32_FA add(.A(baud_addend[baud_bit]),
                    .B(baud_bit == 16 ? 1'b0 : baud_phase[baud_bit]),
                    .CIN(baud_carry[baud_bit]), .SUM(baud_next[baud_bit]),
                    .COUT(baud_carry[baud_bit+1]));
    end endgenerate
    always @(posedge clock) begin
        baud_phase <= baud_next[15:0];
        baud_tick <= baud_next[16];
    end

    wire [7:0] byte_a, byte_b, byte_c;
    wire valid_a, valid_b, valid_c;

    uart_rx_12x #(.TICKS_PER_BIT(RX_TICKS)) receive_a (
        .clock(clock), .tick(baud_tick), .rx(rx_a), .data(byte_a), .valid(valid_a));
    uart_rx_12x #(.TICKS_PER_BIT(RX_TICKS)) receive_b (
        .clock(clock), .tick(baud_tick), .rx(rx_b), .data(byte_b), .valid(valid_b));
    uart_rx_12x #(.TICKS_PER_BIT(RX_TICKS)) receive_c (
        .clock(clock), .tick(baud_tick), .rx(rx_c), .data(byte_c), .valid(valid_c));

    // Each channel has a real one-byte elastic store.  Keeping the receiver's
    // capture register separate from the shared transmit cone is intentional:
    // using the capture register for both roles simulated correctly but
    // corrupted simultaneous B/C traffic on silicon.
    reg [7:0] buffer_a = 0, buffer_b = 0, buffer_c = 0;
    reg       pending_a = 0, pending_b = 0, pending_c = 0;
    reg       overflow = 0;

    reg       tx_start = 0;
    reg [7:0] tx_data = 0;
    // Store the next preferred channel, not the previous grant. The fabric
    // powers registers up at zero, so channel A is selected first without
    // relying on a nonzero Verilog initializer.
    reg [1:0] next_grant = 0;
    reg wait_batch_tick = 0;
    reg batch_tick_seen = 0;
    reg batch_ready = 0;
    wire      tx_busy;

    uart_tx_1x transmit (
        .clock(clock), .tick(baud_tick), .start(tx_start), .data(tx_data),
        .tx(tx), .busy(tx_busy));

    // Registered one-hot service decision.  The original combinational
    // priority tree was correct in RTL simulation but its multi-pending input
    // states corrupted B/C on silicon.  Looking at one pending bit per cycle
    // makes the scheduler small and deterministic; two empty scan cycles are
    // negligible beside one UART frame.
    wire launch_window = !tx_busy && !tx_start;
    wire any_pending = pending_a || pending_b || pending_c;
    wire arbitration_ready = launch_window && batch_ready;
    wire serve_a = arbitration_ready && next_grant == 0 && pending_a;
    wire serve_b = arbitration_ready && next_grant == 1 && pending_b;
    wire serve_c = arbitration_ready && next_grant == 2 && pending_c;

    always @(posedge clock) begin
        tx_start <= 0;
        if (!any_pending) begin
            wait_batch_tick <= 0;
            batch_tick_seen <= 0;
            batch_ready <= 0;
        end else if (!wait_batch_tick && !batch_tick_seen && !batch_ready) begin
            // Independent input synchronizers can make nominally simultaneous
            // frames finish on adjacent 12x ticks.  Wait through one complete
            // tick, then one more fabric edge so the late valid pulse reaches
            // its pending bit before the pointer is allowed to scan.
            wait_batch_tick <= 1;
        end else if (wait_batch_tick && baud_tick) begin
            wait_batch_tick <= 0;
            batch_tick_seen <= 1;
        end else if (batch_tick_seen) begin
            batch_tick_seen <= 0;
            batch_ready <= 1;
        end
        if (arbitration_ready && any_pending) begin
            case (next_grant)
                0: next_grant <= 1;
                1: next_grant <= 2;
                default: next_grant <= 0;
            endcase
        end
        if (serve_a) begin tx_data <= buffer_a; tx_start <= 1; end
        else if (serve_b) begin tx_data <= buffer_b; tx_start <= 1; end
        else if (serve_c) begin tx_data <= buffer_c; tx_start <= 1; end

        if (valid_a && (!pending_a || serve_a)) buffer_a <= byte_a;
        if (valid_b && (!pending_b || serve_b)) buffer_b <= byte_b;
        if (valid_c && (!pending_c || serve_c)) buffer_c <= byte_c;

        case ({valid_a, serve_a})
            2'b10: if (!pending_a) begin pending_a <= 1; end
                   else overflow <= 1;
            2'b01: pending_a <= 0;
            2'b11: pending_a <= 1;
        endcase
        case ({valid_b, serve_b})
            2'b10: if (!pending_b) begin pending_b <= 1; end
                   else overflow <= 1;
            2'b01: pending_b <= 0;
            2'b11: pending_b <= 1;
        endcase
        case ({valid_c, serve_c})
            2'b10: if (!pending_c) begin pending_c <= 1; end
                   else overflow <= 1;
            2'b01: pending_c <= 0;
            2'b11: pending_c <= 1;
        endcase
    end
endmodule

module uart_rx_12x #(
    parameter integer TICKS_PER_BIT = 12
) (
    input wire clock,
    input wire tick,
    input wire rx,
    output reg [7:0] data,
    output reg valid = 0
);
    localparam [1:0] IDLE=0, START=1, BITS=2, STOP=3;
    reg sync0 = 1, sync1 = 1;
    // Fabric configuration clears registers to zero. Preserve this binary
    // encoding so IDLE=0 remains a legal power-up state; one-hot recoding
    // would power up as an invalid all-zero state and never receive a frame.
    (* fsm_encoding = "none" *) reg [1:0] state = IDLE;
    reg [3:0] phase = 0;
    reg [2:0] bit_number = 0;
    reg [7:0] shift = 0;

    always @(posedge clock) begin
        sync0 <= rx;
        sync1 <= sync0;
        valid <= 0;
        case (state)
            IDLE: if (!sync1) begin state <= START; phase <= 0; end
            START: if (tick) begin
                if (phase == TICKS_PER_BIT/2-1) begin
                    phase <= 0;
                    if (!sync1) begin state <= BITS; bit_number <= 0; end
                    else state <= IDLE;
                end else phase <= phase + 1'b1;
            end
            BITS: if (tick) begin
                if (phase == TICKS_PER_BIT-1) begin
                    phase <= 0;
                    shift <= {sync1, shift[7:1]};
                    if (bit_number == 7) state <= STOP;
                    else bit_number <= bit_number + 1'b1;
                end else phase <= phase + 1'b1;
            end
            default: if (tick) begin
                if (phase == TICKS_PER_BIT-1) begin
                    phase <= 0; state <= IDLE;
                    if (sync1) begin data <= shift; valid <= 1; end
                end else phase <= phase + 1'b1;
            end
        endcase
    end
endmodule

module uart_tx_1x (
    input wire clock,
    input wire tick,
    input wire start,
    input wire [7:0] data,
    output wire tx,
    output reg busy = 0
);
    reg [3:0] bit_number = 0;
    reg [9:0] frame = 10'h3ff;
    assign tx = busy ? frame[0] : 1'b1;

    always @(posedge clock) begin
        if (!busy) begin
            if (start) begin
                frame <= {1'b1, data, 1'b0};
                bit_number <= 0; busy <= 1;
            end
        end else if (tick) begin
            if (bit_number == 9)
                busy <= 0;
            else begin
                frame <= {1'b1, frame[9:1]};
                bit_number <= bit_number + 1'b1;
            end
        end
    end
endmodule

`ifdef SIMULATION
module AG32_FA(input wire A, input wire B, input wire CIN,
               output wire SUM, output wire COUT);
    assign {COUT, SUM} = {1'b0, A} + {1'b0, B} + {1'b0, CIN};
endmodule
`else
(* blackbox *) module AG32_FA(input wire A, input wire B, input wire CIN,
                              output wire SUM, output wire COUT);
endmodule
`endif
