// One-channel receive/data/transmit probe using the exact serial-mux modules.
// The existing uart_rx_probe PCFs select PIN_10, PIN_11, or PIN_15 as `rx`;
// PIN_16 carries the decoded byte back at four times the input rate.
`define AGAMEMNON_SERIAL_MUX_LIBRARY
`include "examples/serial_mux/serial_mux.v"

(* top *) module top(input wire clock, input wire rx, output wire seen);
    wire rx_fabric;
    wire [7:0] data;
    wire strobe, token, busy, done;
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf(
        .I({3'b000, rx}), .Q(rx_fabric));
    uart_rx #(.CLK_DIV(1024)) receiver(
        .clock(clock), .rx(rx_fabric), .data(data), .strobe(strobe), .token(token));
    uart_tx #(.CLK_DIV(256)) sender(
        .clock(clock), .load(strobe), .data(data), .busy(busy), .done(done), .tx(seen));
endmodule
