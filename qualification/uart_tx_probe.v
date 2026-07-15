// Transmitter/fixture isolation: after roughly eight input-bit periods, emit
// known A, B, C bytes at the demo's 256-cycle output divider.
`define AGAMEMNON_SERIAL_MUX_LIBRARY
`include "examples/serial_mux/serial_mux.v"

(* top *) module top(input wire clock, output wire tx);
    reg [13:0] delay_count;
    reg [1:0] sent;
    reg load;
    reg [7:0] data;
    wire busy;

    uart_tx #(.CLK_DIV(256)) sender(
        .clock(clock), .load(load), .data(data), .busy(busy), .tx(tx));

    always @(posedge clock) begin
        load <= 1'b0;
        if (!delay_count[13]) begin
            delay_count <= delay_count + 1'b1;
        end else if (!busy && !load && sent != 3) begin
            case (sent)
                0: data <= 8'h41;
                1: data <= 8'h42;
                default: data <= 8'h43;
            endcase
            sent <= sent + 1'b1;
            load <= 1'b1;
        end
    end
endmodule
