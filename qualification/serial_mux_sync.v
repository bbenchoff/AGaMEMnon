// Archived, non-qualified buffered UART concentrator experiment. Do not use as
// an example: the current shipped serial_mux is the collision-free idle-high
// merger, whose non-overlap requirement is explicit and hardware-qualified.
//
// The three 8N1 inputs start and
// remain bit-aligned (as produced by the Pico fixture). Their bits are captured
// directly into the payload register that is subsequently shifted onto TX, so
// there is no parallel register-bank transfer.
(* top *) module top(
    input wire clock,
    input wire rx_a,
    input wire rx_b,
    input wire rx_c,
    output wire tx
);
    wire a, b, c;
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf_a(.I({3'b0, rx_a}), .Q(a));
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf_b(.I({3'b0, rx_b}), .Q(b));
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf_c(.I({3'b0, rx_c}), .Q(c));

    localparam [1:0] IDLE=0, START=1, DATA=2, STOP=3;
    (* fsm_encoding = "none" *) reg [1:0] rx_state;
    reg [11:0] rx_count;
    reg [2:0] rx_bit;
    reg [23:0] payload;

    reg tx_active;
    reg [8:0] tx_count;
    reg [3:0] tx_sub;
    reg [1:0] tx_channel;

    assign tx = !tx_active ? 1'b1 :
                (tx_sub == 0) ? 1'b0 :
                (tx_sub == 9) ? 1'b1 : payload[0];

    always @(posedge clock) begin
        case (rx_state)
            IDLE: if (!a) begin rx_state <= START; rx_count <= 0; end
            START: if (rx_count[9]) begin
                rx_count <= 0;
                if (!a) begin rx_state <= DATA; rx_bit <= 0; end
                else rx_state <= IDLE;
            end else rx_count <= rx_count + 1'b1;
            DATA: if (rx_count[10]) begin
                rx_count <= 0;
                payload[rx_bit]      <= a;
                payload[8 + rx_bit]  <= b;
                payload[16 + rx_bit] <= c;
                if (rx_bit == 7) rx_state <= STOP;
                else rx_bit <= rx_bit + 1'b1;
            end else rx_count <= rx_count + 1'b1;
            default: if (rx_count[10]) begin
                rx_state <= IDLE;
                if (a && b && c && !tx_active) begin
                    tx_active <= 1'b1;
                    tx_count <= 0;
                    tx_sub <= 0;
                    tx_channel <= 0;
                end
            end else rx_count <= rx_count + 1'b1;
        endcase

        if (tx_active) begin
            if (tx_count[8]) begin
                tx_count <= 0;
                if (tx_sub >= 1 && tx_sub <= 8)
                    payload <= {1'b0, payload[23:1]};
                if (tx_sub == 9) begin
                    if (tx_channel == 2)
                        tx_active <= 1'b0;
                    else begin
                        tx_channel <= tx_channel + 1'b1;
                        tx_sub <= 0;
                    end
                end else begin
                    tx_sub <= tx_sub + 1'b1;
                end
            end else tx_count <= tx_count + 1'b1;
        end
    end
endmodule
